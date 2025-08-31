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


class ImageStitchingAndPreprocessing:
    @staticmethod
    def _load_cv2_with_exif(path: str) -> np.ndarray:
        """Read image honoring EXIF orientation and return BGR for OpenCV."""
        pil = Image.open(path)
        pil = ImageOps.exif_transpose(pil)       # respect EXIF orientation
        if pil.mode not in ("RGB", "L"):
            pil = pil.convert("RGB")
        arr = np.array(pil)
        if arr.ndim == 2:
            arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
        else:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        # Heuristic: receipts should be portrait; rotate if clearly landscape
        h, w = arr.shape[:2]
        if w > h:
            arr = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
        return arr

    @staticmethod
    def stitch_receipts(img_paths):
        """Stitch multiple receipt images vertically with overlap detection."""
        stitched = None
        for path in img_paths:
            img = ImageStitchingAndPreprocessing._load_cv2_with_exif(path)
            if stitched is None:
                stitched = img
                continue

            # use a safe slice height (min of 200 or 1/4 of current height)
            slice_h = max(40, min(200, stitched.shape[0] // 4))
            template = cv2.cvtColor(stitched[-slice_h:], cv2.COLOR_BGR2GRAY)
            gray_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            res = cv2.matchTemplate(gray_img, template, cv2.TM_CCOEFF_NORMED)
            _, _, _, max_loc = cv2.minMaxLoc(res)
            y_offset = max_loc[1] + template.shape[0]

            img_cropped = img[y_offset:] if y_offset < img.shape[0] else img
            stitched = cv2.vconcat([stitched, img_cropped])

        return stitched

    @staticmethod
    def deskew_image(cv_img, max_correction_deg: float = 12.0):
        """Deskew but clamp extreme angles to avoid accidental 90° flips."""
        gray = cv_img if cv_img.ndim == 2 else cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        gray_inv = cv2.bitwise_not(gray)
        thresh = cv2.threshold(gray_inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

        coords = np.column_stack(np.where(thresh > 0))
        if coords.size == 0:
            return cv_img  # nothing to compute, return as-is

        angle = cv2.minAreaRect(coords)[-1]
        angle = -(90 + angle) if angle < -45 else -angle

        if abs(angle) > max_correction_deg:
            angle = 0.0  # too big, likely wrong; don't rotate

        (h, w) = cv_img.shape[:2]
        M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(cv_img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    @staticmethod
    def preprocess_for_ocr(cv_img):
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)
        thresh = cv2.adaptiveThreshold(
            denoised, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        pil_img = Image.fromarray(thresh)
        return ImageOps.autocontrast(pil_img, cutoff=2)


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
