"""
    PIL Image Preprocessor module
"""

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import cv2
import numpy as np
import logging
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from config import setup_logging
from schemas import StitchingPlan
import logging

setup_logging()
logger = logging.getLogger(__name__)

class ProcessingMode(Enum):
    """Image processing quality modes"""
    FAST = "fast"
    BALANCED = "balanced"
    QUALITY = "quality"
    CUSTOM = "custom"


@dataclass
class EnhancementConfig:
    """Configuration for image enhancement"""
    mode: ProcessingMode = ProcessingMode.FAST
    target_width: int = 2400
    contrast_factor: float = 1.5 # between 1.5–2.5 depending on OCR results
    brightness_factor: float = 1.1
    sharpness_factor: float = 2.0
    jpeg_quality: int = 95
    enable_auto_orient: bool = True
    enable_deskew: bool = False  # PIL doesn't have built-in deskew


logger = logging.getLogger(__name__)

class IntelligentReceiptStitcher:
    """Execute LLM-generated stitching plan with OpenCV"""

    # Fixed JPEG quality for best OCR results
    JPEG_QUALITY = 95

    @staticmethod
    def stitch_with_plan(img1_bytes: bytes, img2_bytes: bytes, plan: StitchingPlan) -> bytes:
        """Execute stitching according to LLM-generated plan."""
        logger.info(f"Executing stitching plan: {plan}")

        try:
            # Convert to OpenCV format
            img1 = IntelligentReceiptStitcher._bytes_to_cv2(img1_bytes)
            img2 = IntelligentReceiptStitcher._bytes_to_cv2(img2_bytes)

            # Apply rotations if needed
            if plan.top_rotate_deg > 0:
                img1 = IntelligentReceiptStitcher._rotate_image(img1, plan.top_rotate_deg)
                logger.info(f"Rotated top image by {plan.top_rotate_deg} degrees")

            if plan.bottom_rotate_deg > 0:
                img2 = IntelligentReceiptStitcher._rotate_image(img2, plan.bottom_rotate_deg)
                logger.info(f"Rotated bottom image by {plan.bottom_rotate_deg} degrees")

            # Remove exact overlap - no CV detection needed
            img2_cropped = IntelligentReceiptStitcher._remove_overlap_precise(
                img2,
                plan.crop_pixels_from_top
            )

            # Stitch images
            stitched = cv2.vconcat([img1, img2_cropped])
            logger.info(f"Stitched images: final size {stitched.shape}")

            # Apply enhancements
            if plan.enhance_contrast != 1.0 or plan.enhance_brightness != 1.0:
                stitched = IntelligentReceiptStitcher._apply_enhancements(
                    stitched,
                    plan.enhance_contrast,
                    plan.enhance_brightness
                )

            if plan.background_threshold is not None:
                stitched = IntelligentReceiptStitcher._crop_background(stitched, plan.background_threshold)
            else:
                stitched = IntelligentReceiptStitcher._auto_bbox_crop(stitched)

            return IntelligentReceiptStitcher._cv2_to_bytes(stitched)

        except Exception as e:
            logger.error(f"Stitching with plan failed: {e}")
            raise

    @staticmethod
    def _bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
        """Convert image bytes to OpenCV format with EXIF handling"""
        pil_img = Image.open(io.BytesIO(image_bytes))
        pil_img = ImageOps.exif_transpose(pil_img)  # Handle EXIF orientation

        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")

        arr = np.array(pil_img)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _cv2_to_bytes(img: np.ndarray) -> bytes:
        """Convert OpenCV image to JPEG bytes with maximum quality"""
        success, buffer = cv2.imencode(
            '.jpg',
            img,
            [cv2.IMWRITE_JPEG_QUALITY, IntelligentReceiptStitcher.JPEG_QUALITY]
        )
        if not success:
            raise ValueError("Failed to encode image")
        return buffer.tobytes()

    @staticmethod
    def _rotate_image(img: np.ndarray, degrees: int) -> np.ndarray:
        """Rotate image by specified degrees (90, 180, or 270)"""
        if degrees == 90:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif degrees == 180:
            return cv2.rotate(img, cv2.ROTATE_180)
        elif degrees == 270:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        else:
            return img  # No rotation for 0 degrees

    @staticmethod
    def _remove_overlap_precise(img2: np.ndarray, crop_pixels: int) -> np.ndarray:
        """
        Remove exact number of pixels from top of second image as detected by LLM.

        Args:
            img2: Second (bottom) image
            crop_pixels: Exact pixels to crop from top (from LLM analysis)

        Returns:
            Cropped second image
        """
        if crop_pixels <= 0:
            logger.info("No overlap detected by LLM - no cropping needed")
            return img2

        if crop_pixels >= img2.shape[0]:
            logger.error(f"LLM detected crop pixels ({crop_pixels}) >= image height ({img2.shape[0]})")
            logger.error("This indicates either LLM analysis error or corrupted image dimensions")
            raise ValueError(
                f"Cannot crop {crop_pixels} pixels from image with height {img2.shape[0]}. "
                f"LLM analysis may be incorrect or image corrupted."
            )

        # Crop exactly what LLM detected
        cropped = img2[crop_pixels:]
        logger.info(f"LLM-directed precise crop: removed {crop_pixels}px from top of second image")
        logger.info(f"Image dimensions: {img2.shape} -> {cropped.shape}")

        return cropped

    @staticmethod
    def _apply_enhancements(img: np.ndarray, contrast: float, brightness: float) -> np.ndarray:
        """Apply contrast and brightness enhancements to image"""
        # Convert to PIL for easier enhancement
        pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

        # Apply contrast
        if contrast != 1.0:
            enhancer = ImageEnhance.Contrast(pil_img)
            pil_img = enhancer.enhance(contrast)

        # Apply brightness
        if brightness != 1.0:
            enhancer = ImageEnhance.Brightness(pil_img)
            pil_img = enhancer.enhance(brightness)

        # Convert back to OpenCV
        arr = np.array(pil_img)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    @staticmethod
    def _crop_background(img: np.ndarray, threshold: int) -> np.ndarray:
        """
        Crop white/light background from receipt edges.

        Args:
            img: Input image
            threshold: Pixel value threshold (e.g., 220 for light backgrounds)

        Returns:
            Cropped image with background removed
        """
        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Create binary mask (non-background pixels)
        _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)

        # Find contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        if contours:
            # Get bounding box of all contours
            x, y, w, h = cv2.boundingRect(np.concatenate(contours))

            # Add small padding
            padding = 10
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(img.shape[1] - x, w + 2 * padding)
            h = min(img.shape[0] - y, h + 2 * padding)

            # Crop image
            cropped = img[y:y+h, x:x+w]
            logger.info(f"Cropped background: original {img.shape} -> cropped {cropped.shape}")
            return cropped
        else:
            logger.warning("No content found for background cropping")
            return img

    @staticmethod
    def _auto_bbox_crop(img: np.ndarray) -> np.ndarray:
        """
        Automatically detect and crop receipt content using simple thresholding.

        Args:
            img: Input image in OpenCV format

        Returns:
            Cropped image containing only the receipt content
        """
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Use Otsu's method to find optimal threshold automatically
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

            # Find all non-zero (content) pixels
            coords = cv2.findNonZero(binary)
            if coords is None:
                return img

            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(coords)

            # Add small padding and ensure within bounds
            padding = 10
            x = max(0, x - padding)
            y = max(0, y - padding)
            w = min(img.shape[1] - x, w + 2 * padding)
            h = min(img.shape[0] - y, h + 2 * padding)

            cropped = img[y:y+h, x:x+w]
            logger.info(f"Auto bbox crop: {img.shape} -> {cropped.shape}")
            return cropped

        except Exception as e:
            logger.warning(f"Auto bbox failed: {e}")
            return img


@dataclass
class MatchResult:
    overlap: int
    score: float

class IntelligentReceiptStitcherAlt:
    """
    Deterministic executor for the LLM StitchingPlan.
    - Rotates images (90° steps)
    - Searches vertical overlap in [min_overlap_px, max_overlap_px]
    - Stitches with seam at best match (lowest MAD)
    - Optional background crop
    - Enhancement (contrast, brightness)
    """

    def stitch_with_plan(self, img1_bytes: bytes, img2_bytes: bytes, plan: StitchingPlan) -> bytes:
        top = Image.open(io.BytesIO(img1_bytes)).convert("RGB")
        bottom = Image.open(io.BytesIO(img2_bytes)).convert("RGB")

        # Rotate in 90° steps
        if plan.top_rotate_deg:
            top = top.rotate(-plan.top_rotate_deg, expand=True)
        if plan.bottom_rotate_deg:
            bottom = bottom.rotate(-plan.bottom_rotate_deg, expand=True)

        # Normalize widths (small scale alignment to same width)
        top, bottom = self._match_widths(top, bottom)

        # Find overlap
        best = self._find_best_vertical_overlap(top, bottom, plan.min_overlap_px, plan.max_overlap_px)

        # Compose by removing overlap from bottom
        stitched = self._compose_remove_overlap(top, bottom, best.overlap)

        # Optional background crop
        if plan.background_threshold is not None:
            stitched = self._crop_background_by_threshold(stitched, plan.background_threshold)

        # Enhancements (order: contrast then brightness)
        stitched = ImageEnhance.Contrast(stitched).enhance(plan.enhance_contrast)
        stitched = ImageEnhance.Brightness(stitched).enhance(plan.enhance_brightness)

        # Encode JPEG
        out = io.BytesIO()
        stitched.save(out, format="JPEG", quality=95, optimize=True)
        return out.getvalue()

    # ---------- helpers ----------

    def _match_widths(self, top: Image.Image, bottom: Image.Image) -> Tuple[Image.Image, Image.Image]:
        tw, bw = top.width, bottom.width
        if tw == bw:
            return top, bottom
        # If widths differ <=5%, scale the narrower to match the wider to stabilize overlap search
        if abs(tw - bw) / max(tw, bw) <= 0.05:
            target = max(tw, bw)
            if tw < target:
                top = top.resize((target, int(top.height * target / tw)), Image.Resampling.BICUBIC)
            if bw < target:
                bottom = bottom.resize((target, int(bottom.height * target / bw)), Image.Resampling.BICUBIC)
        else:
            # Otherwise pad the narrower with white margins to match widths (avoids distortion)
            target = max(tw, bw)
            top = ImageOps.pad(top, (target, top.height), color="white", centering=(0.5, 0))
            bottom = ImageOps.pad(bottom, (target, bottom.height), color="white", centering=(0.5, 0))
        return top, bottom

    def _find_best_vertical_overlap(
        self, top: Image.Image, bottom: Image.Image, min_ov: int, max_ov: int
    ) -> MatchResult:
        top_np = np.asarray(top.convert("L"))
        bot_np = np.asarray(bottom.convert("L"))
        # Clip search window to actual image sizes
        min_ov = int(max(10, min_ov))
        max_ov = int(min(max_ov, min(top_np.shape[0], bot_np.shape[0], 4000)))

        # Compare the last `k` rows of top to first `k` rows of bottom using Mean Absolute Difference
        best_k, best_score = min_ov, float("inf")
        for k in range(min_ov, max_ov + 1):
            t_band = top_np[-k:, :]
            b_band = bot_np[:k, :]
            # Normalize widths if padding caused slight differences
            m = min(t_band.shape[1], b_band.shape[1])
            score = np.mean(np.abs(t_band[:, :m].astype(np.int16) - b_band[:, :m].astype(np.int16)))
            if score < best_score:
                best_k, best_score = k, score

        return MatchResult(overlap=best_k, score=best_score)

    def _compose_remove_overlap(self, top: Image.Image, bottom: Image.Image, overlap: int) -> Image.Image:
        w = max(top.width, bottom.width)
        # Ensure same width (pad if needed)
        if top.width != w:
            top = ImageOps.pad(top, (w, top.height), color="white", centering=(0.5, 0))
        if bottom.width != w:
            bottom = ImageOps.pad(bottom, (w, bottom.height), color="white", centering=(0.5, 0))
        # Crop away the overlapping rows from the top of bottom
        bottom_cropped = bottom.crop((0, overlap, w, bottom.height))
        # Stack
        out = Image.new("RGB", (w, top.height + bottom_cropped.height), "white")
        out.paste(top, (0, 0))
        out.paste(bottom_cropped, (0, top.height))
        return out

    def _crop_background_by_threshold(self, img: Image.Image, thr: int) -> Image.Image:
        gray = np.asarray(img.convert("L"))
        mask = gray < thr  # True where content is darker than background
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        if rows.size == 0 or cols.size == 0:
            return img
        y0, y1 = int(rows.min()), int(rows.max())
        x0, x1 = int(cols.min()), int(cols.max())
        # Add a tiny margin back to avoid cutting characters
        pad = 6
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(img.width - 1, x1 + pad); y1 = min(img.height - 1, y1 + pad)
        return img.crop((x0, y0, x1 + 1, y1 + 1))


class ImagePreprocessorPillow:
    """
    Lightweight preprocessor using only PIL.
    """

    def __init__(self, config: Optional[EnhancementConfig] = None):
        self.config = config or EnhancementConfig()
        logger.info(f"ImagePreprocessorLite initialized with mode: {self.config.mode}")

    def enhance_image(self, image_data: bytes) -> bytes:
        """
        Main enhancement method using PIL only

        Args:
            image_data: Input image as bytes

        Returns:
            Enhanced image as bytes
        """
        try:
            # Validate input
            if not image_data or len(image_data) == 0:
                raise ValueError("Empty image data provided")

            # Open image with PIL
            img = Image.open(io.BytesIO(image_data))
            logger.info(f"Processing image: {img.size}, mode: {img.mode}")

            # Auto-orient based on EXIF
            if self.config.enable_auto_orient:
                img = self._auto_orient(img)

            # Resize for optimal OCR
            img = self._resize_for_ocr(img)

            # # Convert to RGB if necessary (some enhancements need it)
            # if img.mode not in ('RGB', 'L'):
            #     img = img.convert('RGB')

            # Apply enhancements based on mode
            if self.config.mode == ProcessingMode.FAST:
                img = self._fast_enhancement(img)
            elif self.config.mode == ProcessingMode.BALANCED:
                img = self._balanced_enhancement(img)
            elif self.config.mode == ProcessingMode.CUSTOM:
                img = self._custom_enhancement(img)
            else:  # QUALITY
                img = self._quality_enhancement(img)

            # Convert to grayscale for better OCR
            if img.mode != 'L':
                img = img.convert('L')

            # Final sharpening
            img = self._sharpen(img)

            # Convert back to bytes
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=self.config.jpeg_quality, optimize=True)
            enhanced_bytes = output.getvalue()

            logger.info(f"Enhancement complete. Output size: {len(enhanced_bytes)} bytes")
            return enhanced_bytes

        except Exception as e:
            logger.error(f"Image enhancement failed: {str(e)}")
            return image_data  # Return original on failure

    def _auto_orient(self, img: Image.Image) -> Image.Image:
        """Auto-orient image based on EXIF data"""
        try:
            img = ImageOps.exif_transpose(img)
            return img
        except Exception as e:
            logger.warning(f"Auto-orientation failed: {e}")
            return img

    def _resize_for_ocr(self, img: Image.Image) -> Image.Image:
        """Resize image to optimal width for OCR"""
        width, height = img.size

        if self.config.target_width * 0.7 <= width <= self.config.target_width * 1.3:
            return img

        scale = self.config.target_width / width
        scale = max(0.5, min(scale, 3.0))

        new_width = int(width * scale)
        new_height = int(height * scale)

        # Use high-quality resampling
        resample = Image.Resampling.LANCZOS

        resized = img.resize((new_width, new_height), resample)
        logger.info(f"Resized from {width}x{height} to {new_width}x{new_height}")

        return resized

    def _fast_enhancement(self, img: Image.Image) -> Image.Image:
        """Fast mode: Basic adjustments only"""
        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(self.config.contrast_factor)

        # Enhance brightness
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(self.config.brightness_factor)

        return img

    def _balanced_enhancement(self, img: Image.Image) -> Image.Image:
        """Balanced mode: Standard enhancements"""
        # Remove noise
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(self.config.contrast_factor)

        # Enhance brightness
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(self.config.brightness_factor)

        # Edge enhancement
        img = img.filter(ImageFilter.EDGE_ENHANCE)

        # Auto contrast
        img = ImageOps.autocontrast(img, cutoff=2)

        return img

    def _quality_enhancement(self, img: Image.Image) -> Image.Image:
        """Quality mode: Maximum enhancements"""
        # Denoise with median filter
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # Unsharp mask for clarity
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150))

        # Enhance contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(self.config.contrast_factor * 1.2)

        # Enhance brightness
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(self.config.brightness_factor)

        # Edge enhancement
        img = img.filter(ImageFilter.EDGE_ENHANCE_MORE)

        # Auto contrast and equalize
        img = ImageOps.autocontrast(img, cutoff=1)

        # Convert to grayscale if not already
        if img.mode != 'L':
            img = img.convert('L')

        # Apply histogram equalization
        img = ImageOps.equalize(img)

        # Final sharpening
        enhancer = ImageEnhance.Sharpness(img)
        img = enhancer.enhance(self.config.sharpness_factor)

        return img

    def _sharpen(self, img: Image.Image) -> Image.Image:
        """Apply sharpening filter"""
        try:
            enhancer = ImageEnhance.Sharpness(img)
            return enhancer.enhance(self.config.sharpness_factor)
        except Exception as e:
            logger.warning(f"Sharpening failed: {e}")
            return img

    def _custom_enhancement(self, img: Image.Image) -> Image.Image:
        """Custom mode: User-defined enhancements"""
        img = ImageOps.grayscale(img)
        img = ImageOps.autocontrast(img, cutoff=2)

        return img
