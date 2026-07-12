"""Jenkins integration for self-improving survey loop.

When the self-improve loop encounters unknown patterns, it triggers
a Jenkins job that analyzes HTML and generates parser extensions.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JENKINS_URL = "http://localhost:8080"
JENKINS_USER = "admin"
CONTAINER_NAME = "jenkins"

JOB_NAME = "survey-html-analyzer"
CONFIG_PATH = "/var/jenkins_home/jobs/{job}/config.xml"

JOB_XML = """<?xml version='1.1' encoding='UTF-8'?>
<project>
  <description>Analyze unknown survey HTML and generate parser extensions</description>
  <properties>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>HTML_FILE</name>
          <defaultValue>{html_file}</defaultValue>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>WORK_ORDER_ID</name>
          <defaultValue>{work_order_id}</defaultValue>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <builders>
    <hudson.tasks.Shell>
      <command>#!/bin/bash
set -e
pip install beautifulsoup4 2>/dev/null || true
cat &gt; /tmp/analyze.py &lt;&lt; PYEOF
import sys, json
from pathlib import Path
sys.path.insert(0, "/home/dduckbeagy/survey_dd")
try:
    from bs4 import BeautifulSoup
    from survey_auto.self_improve.generator import extend_parser
    html_file, wo_id = sys.argv[1], sys.argv[2]
    html = Path(html_file).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    patterns = []
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        if not name: continue
        opts = [{"value": o.get("value",""), "label": o.get_text(strip=True)}
                for o in sel.find_all("option") if o.get("value")]
        if opts:
            patterns.append({{"type": "select", "variable": name, "options": opts, "text_inputs": []}})
    for inp in soup.find_all("input", type=lambda t: t and t.lower() not in ("radio","checkbox","hidden","submit","button")):
        name = inp.get("name", "")
        if name:
            patterns.append({{"type": "open", "variable": name, "options": [],
                            "text_inputs": [{{"name": name, "label": "", "must": False, "input_type": inp.get("type","text")}}]}})
    if patterns:
        success = extend_parser(patterns)
        result = {{"success": success, "patterns_found": len(patterns)}}
    else:
        result = {{"success": False, "patterns_found": 0, "error": "No patterns detected"}}
    wo_path = Path("/home/dduckbeagy/survey_dd/.omo/work_orders") / f"{{wo_id}}.json"
    if wo_path.exists():
        data = json.loads(wo_path.read_text())
        data["status"] = "completed" if result["success"] else "failed"
        data["result"] = result
        wo_path.write_text(json.dumps(data, indent=2))
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
PYEOF
python3 /tmp/analyze.py "${{HTML_FILE}}" "${{WORK_ORDER_ID}}"
      </command>
    </hudson.tasks.Shell>
  </builders>
</project>"""


def trigger_analysis_job(
    html_file: str,
    work_order_id: str,
    timeout: int = 120,
) -> bool:
    """Trigger Jenkins job to analyze HTML and generate parser extensions."""
    logger.info("Triggering Jenkins analysis job for %s", work_order_id)

    job_config = JOB_XML.format(html_file=html_file, work_order_id=work_order_id)

    if not _upload_job_config(JOB_NAME, job_config):
        logger.error("Failed to upload job config")
        return False

    return _run_job(JOB_NAME, html_file=html_file, work_order_id=work_order_id, timeout=timeout)


def _upload_job_config(job_name: str, config: str) -> bool:
    """Upload job configuration to Jenkins."""
    try:
        cpath = CONFIG_PATH.format(job=job_name)
        subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "mkdir", "-p",
             f"/var/jenkins_home/jobs/{job_name}"],
            capture_output=True, text=True, timeout=10,
        )
        cmd = "cat > " + cpath + " << 'XMLEOF'\n" + config + "\nXMLEOF"
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("Upload failed: %s", e)
        return False


def _run_job(job_name: str, **params) -> bool:
    """Trigger Jenkins job and wait for completion."""
    try:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{JENKINS_URL}/job/{job_name}/buildWithParameters?{param_str}"
        cmd = f'curl -s -X POST "{url}" -u {JENKINS_USER}:'
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.error("Trigger failed: %s", result.stderr)
            return False
        return _wait_for_job(job_name, timeout=120)
    except Exception as e:
        logger.error("Job execution failed: %s", e)
        return False


def _wait_for_job(job_name: str, timeout: int = 120) -> bool:
    """Wait for Jenkins job to complete."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            cmd = f'curl -s "{JENKINS_URL}/job/{job_name}/lastBuild/api/json"'
            result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if not data.get("building", False):
                    ok = data.get("result") == "SUCCESS"
                    logger.info("Job %s: %s", job_name, "SUCCESS" if ok else "FAILED")
                    return ok
            time.sleep(5)
        except Exception:
            time.sleep(5)
    logger.error("Job %s timed out", job_name)
    return False
