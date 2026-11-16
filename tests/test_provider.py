import json
import os
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from queryproof.provider import _compact, _proposal, _request, assist, configuration


class ProviderBoundaryTests(unittest.TestCase):
    def serve(self, payload, status=200, location=None):
        requests = []
        self.requests = requests
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append({"path": self.path, "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))), "authorization": self.headers.get("Authorization")})
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if location:
                    self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def test_malformed_provider_json_is_a_failure(self):
        endpoint = self.serve(b"not json")
        with self.assertRaises(ValueError):
            _request(endpoint, {"messages": []}, 2)

    def test_incomplete_response_is_not_success(self):
        endpoint = self.serve(json.dumps({"message": {"content": "{}"}, "done": False}).encode())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            _request(endpoint, {}, 2)

    def test_oversized_provider_response_is_rejected(self):
        endpoint = self.serve(b" " * 256001)
        with self.assertRaisesRegex(ValueError, "size limit"):
            _request(endpoint, {}, 2)

    def test_external_endpoint_is_not_accepted(self):
        with patch.dict(os.environ, {"QUERYPROOF_OLLAMA_URL": "http://example.com"}):
            with self.assertRaisesRegex(ValueError, "loopback"):
                configuration()

    def test_invented_evidence_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not supplied"):
            _proposal({"sql": "SELECT 1", "finding_ids": ["invented"]}, {}, [], True)

    def test_invented_numeric_claim_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "number absent"):
            _proposal({"sql": "SELECT 1", "explanation": "Revenue is 999."}, {}, [{"total": 100}], True)

    def test_known_evidence_number_and_id_are_accepted(self):
        proposal = _proposal({"sql": "SELECT 1", "explanation": "The observed total is 100.", "finding_ids": ["grain"]}, {"grain": {}}, [{"total": 100}], True)
        self.assertEqual(proposal["finding_ids"], ["grain"])

    def test_contract_changes_cannot_be_smuggled_into_a_proposal(self):
        with self.assertRaisesRegex(ValueError, "contract edits"):
            _proposal({"sql": "SELECT 1", "contract": {}}, {}, [], True)

    def test_unsupported_revision_can_be_returned_to_model(self):
        self.assertEqual(_compact({"status": "unsupported", "original": None, "reference": None})["status"], "unsupported")

    def test_malformed_assistance_preserves_deterministic_result(self):
        endpoint = self.serve(b"not json")
        prior = {"status": "issue found", "checks": [{"id": "grain", "count": 3}]}
        encoded = json.dumps(prior)
        with patch.dict(os.environ, {"QUERYPROOF_OLLAMA_URL": endpoint}):
            result = assist({"tables": {}}, {}, "SELECT 1", prior)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(json.dumps(prior), encoded)
        self.assertIsNone(result["proposal"])

    def test_repeated_tool_requests_stop_at_budget(self):
        endpoint = self.serve(json.dumps({"message": {"content": json.dumps({"action": "inspect_contract"})}, "done": True, "eval_count": 10}).encode())
        with patch.dict(os.environ, {"QUERYPROOF_OLLAMA_URL": endpoint}):
            result = assist({"tables": {}}, {}, "SELECT 1", {"checks": []}, max_tool_calls=2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["activity"]), 2)
        self.assertIn("budget", result["error"])

    def test_cancelled_assistance_never_finishes_successfully(self):
        event = threading.Event()
        event.set()
        result = assist({"tables": {}}, {}, "SELECT 1", {"checks": []}, cancel_event=event)
        self.assertEqual(result["status"], "failed")
        self.assertIn("interrupted", result["error"])

    def test_missing_usage_cannot_bypass_token_budget(self):
        endpoint = self.serve(json.dumps({"message": {"content": json.dumps({"action": "inspect_contract"})}, "done": True}).encode())
        with patch.dict(os.environ, {"QUERYPROOF_OLLAMA_URL": endpoint}):
            result = assist({"tables": {}}, {}, "SELECT 1", {"checks": []})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["activity"]), 3)
        self.assertIn("token limit", result["error"])
        self.assertFalse(result["tokens"]["reported"])

    def test_hosted_configuration_never_contains_secret(self):
        with patch.dict(os.environ, {"QUERYPROOF_PROVIDER": "openai-compatible", "QUERYPROOF_MODEL": "test-model", "QUERYPROOF_API_KEY": "dummy-secret", "QUERYPROOF_API_BASE": "https://api.example.test/v1"}):
            config = configuration()
        self.assertFalse(config["local"])
        self.assertTrue(config["configured"])
        self.assertNotIn("dummy-secret", json.dumps(config))
        self.assertIn("api.example.test", config["disclosure"])

    def test_hosted_endpoint_requires_https(self):
        with patch.dict(os.environ, {"QUERYPROOF_PROVIDER": "openai-compatible", "QUERYPROOF_API_BASE": "http://api.example.test/v1"}):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                configuration()

    def test_hosted_configuration_requires_key_and_explicit_model(self):
        with patch.dict(os.environ, {"QUERYPROOF_PROVIDER": "openai-compatible", "QUERYPROOF_API_BASE": "https://api.example.test/v1", "QUERYPROOF_MODEL": "", "QUERYPROOF_API_KEY": ""}):
            self.assertFalse(configuration()["configured"])

    def test_hosted_request_transforms_protocol_and_usage(self):
        response = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": '{"action":"inspect_contract"}'}}], "usage": {"prompt_tokens": 20, "completion_tokens": 10}}
        endpoint = self.serve(json.dumps(response).encode())
        requested_urls = []

        def transport(request, timeout):
            requested_urls.append(request.full_url)
            forwarded = urllib.request.Request(endpoint + "/chat/completions", data=request.data, headers=dict(request.header_items()))
            return urllib.request.urlopen(forwarded, timeout=timeout)

        payload = {"model": "test-model", "messages": [{"role": "user", "content": "Return JSON"}], "options": {"num_predict": 123}}
        with patch("queryproof.provider._open", side_effect=transport):
            result = _request("https://api.example.test/v1", payload, 2, provider="openai-compatible", api_key="dummy-secret")
        self.assertEqual(requested_urls, ["https://api.example.test/v1/chat/completions"])
        self.assertEqual(self.requests[0]["authorization"], "Bearer dummy-secret")
        self.assertEqual(self.requests[0]["body"]["max_completion_tokens"], 123)
        self.assertEqual(self.requests[0]["body"]["response_format"], {"type": "json_object"})
        self.assertEqual(result["eval_count"], 10)
        self.assertEqual(result["prompt_eval_count"], 20)

    def test_provider_error_does_not_echo_secret(self):
        endpoint = self.serve(b'{"error":"dummy-secret"}', status=401)
        with self.assertRaises(ValueError) as caught:
            _request(endpoint, {"model": "test", "messages": [], "options": {"num_predict": 1}}, 2, provider="openai-compatible", api_key="dummy-secret")
        self.assertNotIn("dummy-secret", str(caught.exception))
        self.assertIn("401", str(caught.exception))

    def test_provider_redirect_cannot_forward_authorization(self):
        endpoint = self.serve(b"", status=302, location="http://127.0.0.1:1/steal")
        with self.assertRaisesRegex(ValueError, "HTTP 302"):
            _request(endpoint, {"model": "test", "messages": [], "options": {"num_predict": 1}}, 2, provider="openai-compatible", api_key="dummy-secret")


if __name__ == "__main__":
    unittest.main()
