# https://github.com/langgenius/dify/blob/main/sdks/python-client/dify_client/client.py

import requests


class DifyClient:
    def __init__(self, api_key, base_url: str = "https://api.dify.ai/v1"):
        self.api_key = api_key
        self.base_url = base_url

    def _send_request(self, method, endpoint, json=None, params=None, stream=False):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self.base_url}{endpoint}"
        response = requests.request(
            method, url, json=json, params=params, headers=headers, stream=stream
        )

        return response

    def _send_request_with_files(self, method, endpoint, data, files):
        headers = {"Authorization": f"Bearer {self.api_key}"}

        url = f"{self.base_url}{endpoint}"
        response = requests.request(
            method, url, data=data, headers=headers, files=files
        )

        return response

    def message_feedback(self, message_id, rating, user):
        data = {"rating": rating, "user": user}
        return self._send_request("POST", f"/messages/{message_id}/feedbacks", data)

    def get_application_parameters(self, user):
        params = {"user": user}
        return self._send_request("GET", "/parameters", params=params)

    def file_upload(self, user, files):
        data = {"user": user}
        return self._send_request_with_files(
            "POST", "/files/upload", data=data, files=files
        )

    def text_to_audio(self, text: str, user: str, streaming: bool = False):
        data = {"text": text, "user": user, "streaming": streaming}
        return self._send_request("POST", "/text-to-audio", data=data)

    def get_meta(self, user):
        params = {"user": user}
        return self._send_request("GET", "/meta", params=params)


class CompletionClient(DifyClient):
    def create_completion_message(self, inputs, response_mode, user, files=None):
        data = {
            "inputs": inputs,
            "response_mode": response_mode,
            "user": user,
            "files": files,
        }
        return self._send_request(
            "POST",
            "/completion-messages",
            data,
            stream=True if response_mode == "streaming" else False,
        )


class WorkflowClient(DifyClient):
    def run(
        self, inputs: dict, response_mode: str = "streaming", user: str = "abc-123"
    ):
        data = {"inputs": inputs, "response_mode": response_mode, "user": user}
        return self._send_request("POST", "/workflows/run", data)

    def stop(self, task_id, user):
        data = {"user": user}
        return self._send_request("POST", f"/workflows/tasks/{task_id}/stop", data)

    def get_result(self, workflow_run_id):
        return self._send_request("GET", f"/workflows/run/{workflow_run_id}")