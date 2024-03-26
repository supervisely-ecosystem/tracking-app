import os

from dotenv import load_dotenv

import supervisely as sly
import supervisely.app.development as sly_app_development


port = "8000"
# Enabling advanced debug mode.
if sly.is_development():
    load_dotenv("local.env")
    team_id = sly.env.team_id()
    load_dotenv(os.path.expanduser("~/supervisely.env"))
    sly_app_development.supervisely_vpn_network(action="up")
    sly_app_development.create_debug_task(team_id, port=port)

api = sly.Api()


def find_debug_task_id(port):
    me = api.user.get_my_info()
    session_name = me.login + "-development"
    module_id = api.app.get_ecosystem_module_id("supervisely-ecosystem/while-true-script-v2")
    sessions = api.app.get_sessions(team_id, module_id, session_name=session_name)
    redirect_requests = {"token": api.token, "port": port}
    task = None
    for session in sessions:
        if (session.details["meta"].get("redirectRequests") == redirect_requests) and (
            session.details["status"] == str(api.app.Status.QUEUED)
        ):
            task = session.details
            if "id" not in task:
                task["id"] = task["taskId"]
            sly.logger.info(f"Debug task already exists: {task['id']}")
            break
    return task["id"]


task_id = None
if sly.is_development():
    task_id = find_debug_task_id(port)
    if task_id is None:
        raise RuntimeError("Debug task not found")
team_id = sly.env.team_id()


class AppState:
    def __init__(self):
        # project
        self.project_id: int = None
        self.project_meta: sly.ProjectMeta = None
        # dataset
        self.dataset_id: int = None
        # video
        self.current_video_id: int = None
        self.current_video_info: sly.api.video_api.VideoInfo
        # frame
        self.current_frame_index: int = None
        # figure
        self.current_figure_id: int = None
        self.figure_changed: dict = {}


STATE = AppState()
NN_URLS = {
    sly.Rectangle.geometry_name(): "http://100.83.184.134:8080",
    sly.Bitmap.geometry_name(): "http://100.83.184.134:8081",
    sly.Polygon.geometry_name(): "http://100.83.184.134:8082",
    sly.Point.geometry_name(): "http://100.83.184.134:8082",
    sly.Polyline.geometry_name(): "http://100.83.184.134:8082",
    sly.GraphNodes.geometry_name(): "http://100.83.184.134:8082",
    # sly.Polygon.geometry_name(): "http://100.83.184.134:8082",
    "smarttool": "http://100.83.184.134:8083",
}


AUTO_TRACK_MODULE_ID = 714
