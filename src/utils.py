from typing import List
import uuid

import cv2
import numpy as np
import supervisely as sly


def get_figure_track_id(figure_id: int) -> str:
    return str(uuid.uuid5(namespace=uuid.NAMESPACE_URL, name=str(figure_id)))


class SmartToolInput:
    def __init__(self, crop: List, positive: List, negative: List, visible: bool = True):
        positive = [
            [point.col, point.row] if isinstance(point, sly.Point) else point for point in positive
        ]
        negative = [
            [point.col, point.row] if isinstance(point, sly.Point) else point for point in negative
        ]
        if isinstance(crop, sly.Rectangle):
            crop = [[crop.left, crop.top], [crop.right, crop.bottom]]
        self.crop = crop
        self.positive = positive
        self.negative = negative
        self.visible = visible

    def to_json(self):
        return {
            "crop": self.crop,
            "positive": self.positive,
            "negative": self.negative,
            "visible": self.visible,
        }

    @classmethod
    def from_json(cls, data: dict):
        return cls(
            crop=data["crop"],
            positive=data["positive"],
            negative=data["negative"],
            visible=data["visible"],
        )


class Meta:
    def __init__(
        self,
        smi: SmartToolInput = None,
        object_id: int = None,
        priority: int = 1,
        project_id: int = None,
        tags: List[str] = None,
        tool: str = None,
        track_id: str = None,
        updated_at: str = None,
    ):
        self.smi = smi.to_json() if isinstance(smi, SmartToolInput) else smi
        self.object_id = object_id
        self.priority = priority
        self.project_id = project_id
        self.tags = tags if tags is not None else []
        self.tool = tool
        self.track_id = track_id
        self.updated_at = updated_at

    def to_json(self):
        return {
            "smartToolInput": self.smi,
            "object_id": self.object_id,
            "priority": self.priority,
            "project_id": self.project_id,
            "tags": self.tags,
            "tool": self.tool,
            "track_id": self.track_id,
            "updated_at": self.updated_at,
        }


class Prediction:

    def __init__(
        self, frame_index: int, geometry_data: dict, geometry_type: str, meta: Meta = None
    ):
        self.frame_index = frame_index
        self.geometry_data = geometry_data
        self.geometry_type = geometry_type
        self.meta = meta

    def to_json(self):
        meta = None
        if self.meta is not None:
            meta = self.meta.to_json() if isinstance(self.meta, Meta) else self.meta

        return {
            "frame_index": self.frame_index,
            "data": self.geometry_data,
            "type": self.geometry_type,
            "meta": meta,
        }


def smoothen_mask(mask: sly.Bitmap, img_size) -> sly.Bitmap:
    sly.logger.debug("smoothing mask")
    canv: np.ndarray = mask.get_mask(img_size)
    canv = canv.astype("uint8")
    kernel = np.ones((img_size[0] * 5 // 480, img_size[1] * 5 // 480), np.uint8)

    # Apply morphological closing to smooth edges
    # pylint: disable=no-member
    canv = cv2.morphologyEx(canv, cv2.MORPH_CLOSE, kernel, iterations=3)
    return sly.Bitmap(canv)


def move_points_relative(
    src_rect: sly.Rectangle, points: List[sly.Point], dst_rect: sly.Rectangle
) -> List[sly.Point]:
    res_points = []
    for point in points:
        w_percent = (point.col - src_rect.left) / src_rect.width
        h_percent = (point.row - src_rect.top) / src_rect.height
        col = int(dst_rect.left + dst_rect.width * w_percent)
        row = int(dst_rect.top + dst_rect.height * h_percent)
        res_points.append(sly.Point(row, col))
    return res_points
