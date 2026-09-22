from __future__ import annotations
import numpy as np


class LocalOCR:
    """Paddle-derived OCR model bundled by RapidOCR, using local ONNX CPU inference.

    No HTTP client and no cloud fallback. Images never leave this process.
    """
    def __init__(self, threads=4):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)

    def read(self, image):
        result, elapsed = self.engine(np.asarray(image.convert('RGB')), use_cls=False)
        lines = []
        for box, text, score in result or []:
            lines.append(dict(text=text, score=float(score), polygon=box,
                              bbox=[min(p[0] for p in box), min(p[1] for p in box),
                                    max(p[0] for p in box), max(p[1] for p in box)]))
        return lines
