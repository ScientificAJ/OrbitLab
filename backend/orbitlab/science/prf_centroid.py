"""Point-source model fitting for difference-image centroid vetting.

NASA's DV pipeline localizes the *transit source* by fitting the Pixel
Response Function to the difference image and comparing that position to the
target star. Image moments (flux-weighted means) answer the same question
crudely: they are biased toward bright neighbors and background gradients,
and their uncertainty comes from cadence scatter rather than the fit itself.

Phase 1A implements the fit with an elliptical 2-D Gaussian + constant
background kernel; mission PRF models (Kepler PRF via lightkurve, TESS PRF
FITS from MAST) can replace the kernel later without changing the fit
machinery or the payload contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.optimize import least_squares

# A point-source fit needs enough pixels to constrain six parameters with
# residual degrees of freedom left for the covariance scale.
_MIN_FINITE_PIXELS = 12


@dataclass(frozen=True)
class PsfFitResult:
    row: float
    col: float
    row_uncertainty: float
    col_uncertainty: float
    amplitude: float
    background: float
    sigma_row: float
    sigma_col: float
    reduced_chi2: float
    converged: bool
    n_pixels: int

    def as_dict(self) -> dict:
        return asdict(self)


def _model(params: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    r0, c0, sigma_r, sigma_c, amplitude, background = params
    return amplitude * np.exp(
        -((rows - r0) ** 2 / (2.0 * sigma_r**2) + (cols - c0) ** 2 / (2.0 * sigma_c**2))
    ) + background


def _moment_initial_guess(image: np.ndarray, finite: np.ndarray) -> tuple[float, float]:
    floor = float(np.nanpercentile(image[finite], 5))
    weights = np.where(finite, image - floor, 0.0)
    weights = np.where(weights > 0, weights, 0.0)
    total = float(np.nansum(weights))
    rows, cols = np.indices(image.shape, dtype=np.float64)
    if total > 0 and np.isfinite(total):
        return (
            float(np.nansum(rows * weights) / total),
            float(np.nansum(cols * weights) / total),
        )
    return (image.shape[0] / 2.0, image.shape[1] / 2.0)


def fit_point_source(
    image: np.ndarray,
    *,
    pixel_noise: np.ndarray | None = None,
    initial: tuple[float, float] | None = None,
    fit_radius: float | None = None,
    kernel=None,
) -> PsfFitResult | None:
    """Fit a point source + flat background to a pixel image.

    `fit_radius` restricts the fitted pixels to a window around the initial
    guess: a single-source model applied to a full cutout containing
    neighbor stars is mis-specified, and localizing the fit keeps the
    neighbor from biasing the target's position. Model mismatch that remains
    inside the window is not grounds for rejection — the covariance is
    scaled by the reduced chi-square, so contamination honestly inflates the
    positional uncertainty instead of silently vetoing the measurement.

    Returns None whenever the data cannot support a trustworthy fit (too few
    pixels, non-convergence, position pinned to the image edge, or a
    degenerate covariance); the caller is expected to fall back to image
    moments and say so in its provenance field.
    """
    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 2:
        return None
    finite = np.isfinite(arr)

    rows, cols = np.indices(arr.shape, dtype=np.float64)
    guess = initial if initial is not None else _moment_initial_guess(arr, finite) if finite.any() else None
    if fit_radius is not None and guess is not None:
        finite = finite & (np.hypot(rows - guess[0], cols - guess[1]) <= fit_radius)
    n_pixels = int(np.count_nonzero(finite))
    if n_pixels < _MIN_FINITE_PIXELS:
        return None
    rows_flat = rows[finite]
    cols_flat = cols[finite]
    values = arr[finite]

    weights = None
    if pixel_noise is not None:
        noise = np.asarray(pixel_noise, dtype=np.float64)
        if noise.shape == arr.shape:
            noise_flat = noise[finite]
            positive = noise_flat[np.isfinite(noise_flat) & (noise_flat > 0)]
            if positive.size:
                floor = max(float(np.nanmedian(positive)) * 1.0e-3, 1.0e-12)
                safe = np.where(np.isfinite(noise_flat) & (noise_flat > 0), noise_flat, floor)
                weights = 1.0 / np.maximum(safe, floor)

    background0 = float(np.nanpercentile(values, 5))
    amplitude0 = max(float(np.nanmax(values)) - background0, 1.0e-12)
    r0, c0 = guess if guess is not None else (arr.shape[0] / 2.0, arr.shape[1] / 2.0)
    max_dim = float(max(arr.shape))
    if kernel is None:
        x0 = np.array([r0, c0, 1.2, 1.2, amplitude0, background0], dtype=np.float64)
        lower = np.array([-0.5, -0.5, 0.3, 0.3, 0.0, -np.inf])
        upper = np.array([arr.shape[0] - 0.5, arr.shape[1] - 0.5, max_dim, max_dim, np.inf, np.inf])
    else:
        # Mission PRF kernel: the profile shape is fixed by the calibration
        # product, so only position, amplitude, and background are free.
        x0 = np.array([r0, c0, amplitude0, background0], dtype=np.float64)
        lower = np.array([-0.5, -0.5, 0.0, -np.inf])
        upper = np.array([arr.shape[0] - 0.5, arr.shape[1] - 0.5, np.inf, np.inf])
    x0 = np.clip(x0, lower + 1.0e-6, upper - 1.0e-6)

    def residuals(params: np.ndarray) -> np.ndarray:
        if kernel is None:
            model = _model(params, rows_flat, cols_flat)
        else:
            model = params[2] * kernel(rows_flat, cols_flat, params[0], params[1]) + params[3]
        res = model - values
        return res * weights if weights is not None else res

    try:
        fit = least_squares(residuals, x0, bounds=(lower, upper), method="trf")
    except (ValueError, np.linalg.LinAlgError):
        return None

    dof = n_pixels - x0.size
    if dof <= 0:
        return None
    reduced_chi2 = float(2.0 * fit.cost / dof)
    if not np.isfinite(reduced_chi2):
        return None

    # Reject fits pinned to the position bounds: the "source" ran off the
    # cutout and the position is the optimizer's wall, not a measurement.
    edge_margin = 1.0e-3
    if (
        fit.x[0] <= lower[0] + edge_margin
        or fit.x[0] >= upper[0] - edge_margin
        or fit.x[1] <= lower[1] + edge_margin
        or fit.x[1] >= upper[1] - edge_margin
    ):
        return None

    # Covariance from the jacobian at the solution, scaled by the residual
    # variance: cov = inv(J^T J) * 2*cost/dof.
    try:
        jtj = fit.jac.T @ fit.jac
        covariance = np.linalg.inv(jtj) * reduced_chi2
    except np.linalg.LinAlgError:
        return None
    position_variances = np.diag(covariance)[:2]
    if not np.all(np.isfinite(position_variances)) or np.any(position_variances < 0):
        return None

    if kernel is None:
        amplitude, background = float(fit.x[4]), float(fit.x[5])
        sigma_row, sigma_col = float(fit.x[2]), float(fit.x[3])
    else:
        amplitude, background = float(fit.x[2]), float(fit.x[3])
        sigma_row = sigma_col = float("nan")
    return PsfFitResult(
        row=float(fit.x[0]),
        col=float(fit.x[1]),
        row_uncertainty=float(np.sqrt(position_variances[0])),
        col_uncertainty=float(np.sqrt(position_variances[1])),
        amplitude=amplitude,
        background=background,
        sigma_row=sigma_row,
        sigma_col=sigma_col,
        reduced_chi2=reduced_chi2,
        converged=bool(fit.success),
        n_pixels=n_pixels,
    )
