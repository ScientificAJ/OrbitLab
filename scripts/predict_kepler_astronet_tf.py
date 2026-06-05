#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.core.framework import attr_value_pb2, graph_pb2, node_def_pb2, tensor_shape_pb2, types_pb2
from tensorflow.core.protobuf import meta_graph_pb2
from tensorflow.python.framework import tensor_util
from tensorflow.python.ops import gen_resource_variable_ops


def _tensor_shape(batch: int, bins: int) -> tensor_shape_pb2.TensorShapeProto:
    return tensor_shape_pb2.TensorShapeProto(
        dim=[
            tensor_shape_pb2.TensorShapeProto.Dim(size=batch),
            tensor_shape_pb2.TensorShapeProto.Dim(size=bins),
            tensor_shape_pb2.TensorShapeProto.Dim(size=1),
        ]
    )


def _placeholder(name: str, batch: int, bins: int) -> node_def_pb2.NodeDef:
    node = node_def_pb2.NodeDef()
    node.name = name
    node.op = "Placeholder"
    node.attr["dtype"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_FLOAT))
    node.attr["shape"].CopyFrom(attr_value_pb2.AttrValue(shape=_tensor_shape(batch, bins)))
    return node


def _const_int_node(name, values):
    node = node_def_pb2.NodeDef()
    node.name = name
    node.op = "Const"
    node.attr["dtype"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_INT32))
    node.attr["value"].CopyFrom(attr_value_pb2.AttrValue(tensor=tensor_util.make_tensor_proto(values, dtype=tf.int32)))
    return node


def _reshape_node(name, input_name, shape_name):
    node = node_def_pb2.NodeDef()
    node.name = name
    node.op = "Reshape"
    node.input.extend([input_name, shape_name])
    node.attr["T"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_FLOAT))
    node.attr["Tshape"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_INT32))
    return node


def _softmax_node(name, input_name):
    node = node_def_pb2.NodeDef()
    node.name = name
    node.op = "Softmax"
    node.input.extend([input_name])
    node.attr["T"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_FLOAT))
    return node


def _base_name(input_name: str) -> str:
    clean = input_name[1:] if input_name.startswith("^") else input_name
    return clean.split(":", 1)[0]


def build_inference_graph(meta_path: Path) -> graph_pb2.GraphDef:
    meta = meta_graph_pb2.MetaGraphDef()
    meta.ParseFromString(meta_path.read_bytes())
    nodes = {node.name: node for node in meta.graph_def.node}
    wanted = set()

    def visit(name: str) -> None:
        base = _base_name(name)
        if base in wanted or base == "IteratorGetNext":
            return
        node = nodes.get(base)
        if node is None:
            return
        wanted.add(base)
        for input_name in node.input:
            visit(input_name)

    visit("predictions")

    graph_def = graph_pb2.GraphDef()
    graph_def.node.extend(
        [
            _placeholder("orbitlab_global_view", 64, 2001),
            _placeholder("orbitlab_local_view", 64, 201),
        ]
    )
    for node in meta.graph_def.node:
        if node.name not in wanted:
            continue
        copied = node_def_pb2.NodeDef()
        copied.CopyFrom(node)
        if copied.op == "EnsureShape":
            copied.op = "Identity"
            shape_attr = copied.attr.get("shape")
            copied.attr.clear()
            if shape_attr is not None and node.input:
                copied.attr["T"].CopyFrom(attr_value_pb2.AttrValue(type=types_pb2.DT_FLOAT))
        if copied.op == "Fill" and "index_type" in copied.attr:
            del copied.attr["index_type"]
        if copied.op == "Cast" and "Truncate" in copied.attr:
            del copied.attr["Truncate"]
        if copied.op == "Conv2D" and "explicit_paddings" in copied.attr:
            del copied.attr["explicit_paddings"]
        if copied.op == "Softmax" and copied.name.endswith("/Softmax"):
            last_dim = 24 if copied.name.startswith("local_view_hidden/") else 59
            graph_def.node.extend(
                [
                    _const_int_node(copied.name + "/flatten_shape", [-1, last_dim]),
                    _reshape_node(copied.name + "/flatten", copied.input[0], copied.name + "/flatten_shape"),
                    _softmax_node(copied.name + "/softmax_2d", copied.name + "/flatten"),
                    _const_int_node(copied.name + "/output_shape", [64, 1, last_dim]),
                    _reshape_node(copied.name, copied.name + "/softmax_2d", copied.name + "/output_shape"),
                ]
            )
            continue
        for index, input_name in enumerate(copied.input):
            control = "^" if input_name.startswith("^") else ""
            clean = input_name[1:] if control else input_name
            if clean == "IteratorGetNext:1":
                copied.input[index] = "{0}orbitlab_global_view".format(control)  # noqa: UP030,UP032
            elif clean == "IteratorGetNext:2":
                copied.input[index] = "{0}orbitlab_local_view".format(control)  # noqa: UP030,UP032
        graph_def.node.extend([copied])
    return graph_def


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the pinned Kepler AstroNet checkpoint in TensorFlow 1.x.")
    parser.add_argument("--checkpoint-prefix", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    arrays = np.load(str(args.input))
    global_view = np.asarray(arrays["global_view"], dtype=np.float32)
    local_view = np.asarray(arrays["local_view"], dtype=np.float32)
    if global_view.shape != (1, 2001, 1) or local_view.shape != (1, 201, 1):
        raise ValueError(
            "unexpected AstroNet tensor shapes: {0}, {1}".format(global_view.shape, local_view.shape)  # noqa: UP030,UP032
        )
    global_batch = np.repeat(global_view, 64, axis=0)
    local_batch = np.repeat(local_view, 64, axis=0)

    graph_def = build_inference_graph(Path(str(args.checkpoint_prefix) + ".meta"))
    graph = tf.Graph()
    with graph.as_default():
        tf.import_graph_def(graph_def, name="")
        reader = tf.train.NewCheckpointReader(str(args.checkpoint_prefix))
        assign_ops = []
        for name in reader.get_variable_to_shape_map():
            try:
                variable = graph.get_tensor_by_name(name + ":0")
            except KeyError:
                continue
            value = reader.get_tensor(name)
            if variable.dtype == tf.resource:
                assign_ops.append(gen_resource_variable_ops.assign_variable_op(variable, value))
            else:
                assign_ops.append(tf.assign(variable, value))
        if not assign_ops:
            raise ValueError("no checkpoint variables are present in the pruned Kepler graph")
        with tf.Session(graph=graph) as session:
            session.run(assign_ops)
            probability = session.run(
                graph.get_tensor_by_name("predictions:0"),
                feed_dict={
                    graph.get_tensor_by_name("orbitlab_global_view:0"): global_batch,
                    graph.get_tensor_by_name("orbitlab_local_view:0"): local_batch,
                },
            )
    payload = {"probability": float(np.asarray(probability).reshape(-1)[0])}
    args.output.write_text(json.dumps(payload, sort_keys=True))
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
