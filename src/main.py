import os
from dotenv import load_dotenv
import pandas as pd
import src.globals as g
import supervisely as sly
import supervisely.app.development as sly_app_development
from supervisely.app.widgets import (
    Container,
    Button,
    Field,
    Table,
    Text,
    Checkbox,
)

table = Table()
run_button = Button("Predict next frame")

layout = Container(
    widgets=[
        table,
        run_button
    ]
)
app = sly.Application(layout=layout)

# Initializing global variables.
api = None
project_meta = None
event_video: sly.Event.ManualSelected.VideoChanged = None
event_figure: sly.Event.ManualSelected.FigureChanged = None
# session_id = None
# dataset_id = None
# video_id = None
# project_id = None

items = None

@app.event(sly.Event.ManualSelected.VideoChanged)
def video_changed(event_api: sly.Api, event: sly.Event.ManualSelected.VideoChanged):
    print("video_changed")
    global api, event_video, project_meta, items
    api = event_api
    event_video = event
    project_meta = sly.ProjectMeta.from_json(api.project.get_meta(event_video.project_id))

    items = get_frame_annotation(event_video.video_id, event_video.frame)
    for item in items:
        item['checked'] = "❌"
    update_table()


@app.event(sly.Event.ManualSelected.FigureChanged)
def figure_changed(event_api: sly.Api, event: sly.Event.ManualSelected.FigureChanged):
    print("figure_changed")
    global event_figure, items

    if event.figure_id is None:
        return
    event_figure = event

    if items is None:
        return

    # find figure in items and check it
    for item in items:
        if item['figure_id'] == event_figure.figure_id:
            item['checked'] = "✅"
            update_table()

    # if added new figure, then add it to items
    if event_figure.figure_id not in [item['figure_id'] for item in items]:
        item = {
            'figure_id': event_figure.figure_id,
            'object_id': event_figure.annotation_object_id,
            'name': event_figure.figure_class_title,
            'checked': "✅"
        }
        items.append(item)
        update_table()


@run_button.click
def predict_next_frame():
    global items
    # table.get_json_state()
    # Table.create_button

    # collect figure ids and object ids
    object_ids = []
    figure_ids = []
    for item in items:
        if item['checked'] == "✅":
            object_ids.append(item['object_id'])
            figure_ids.append(item['figure_id'])

    video_id = event_video.video_id
    frame_index = event_figure.frame
    track_id = 'none'
    direction = 'forward'
    frames_count = 1

    data = {
        "frameIndex": frame_index,
        "frames": frames_count,
        "trackId": track_id,
        "videoId": video_id,
        "objectIds": object_ids,
        "figureIds": figure_ids,
        "direction": direction,
    }

    sly.json.dump_json_file(data, "data.json")

    g.api.task.send_request(51877, "predict", {}, context=data)


def update_table():
    global items
    table.read_pandas(pd.DataFrame(items))

@table.click
def handle_table_click(datapoint: Table.ClickedDataPoint):
    # switch checked state of the clicked row
    global items
    for item in items:
        if item['figure_id'] == datapoint.row['figure_id']:
            if item['checked'] == "✅":
                item['checked'] = "❌"
            else:
                item['checked'] = "✅"
    update_table()


def get_frame_annotation(video_id, frame_idx) -> sly.Frame:
    # Get the video annotation for the specified frame index
    frame_annotation = api.video.annotation.download(video_id)
    kei_id_map = sly.KeyIdMap()
    ann = sly.VideoAnnotation.from_json(frame_annotation, project_meta, kei_id_map)
    
    # Extract the annotation for the given frame index
    frame_annotation = None
    for frame in ann.frames:
        frame: sly.Frame
        if frame.index == frame_idx:
            frame_annotation = frame
            break
    assert frame_annotation is not None, "Frame not found in the annotation"

    # Extract figures from the frame annotation
    items = []
    for figure in frame_annotation.figures:
        if isinstance(figure.geometry, sly.Rectangle) is False:
            continue
        item = {
            'figure_id': kei_id_map.get_figure_id(figure.key()),
            'object_id': kei_id_map.get_object_id(figure.parent_object.key()),
            'name': figure.parent_object.obj_class.name
        }
        items.append(item)
    
    return items