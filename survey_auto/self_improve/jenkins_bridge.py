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
WORKSPACE = "/var/jenkins_home/workspace/survey-auto-extensions"


def trigger_analysis_job(
    html_file: str,
    work_order_id: str,
    timeout: int = 120,
) -> bool:
    """Trigger Jenkins job to analyze HTML and generate parser extensions.
    
    Returns True if job succeeded.
    """
    logger.info("Triggering Jenkins analysis job for %s", work_order_id)
    
    # Create job config XML
    job_config = _create_job_config(html_file, work_order_id)
    
    # Upload config to Jenkins
    if not _upload_job_config("survey-html-analyzer", job_config):
        logger.error("Failed to upload job config")
        return False
    
    # Trigger the job with parameters
    return _run_job("survey-html-analyzer", html_file=html_file, work_order_id=work_order_id, timeout=timeout)


def _create_job_config(html_file: str, work_order_id: str) -> str:
    """Create Jenkins job XML config for HTML analysis."""
    return f'''<?xml version='1.1' encoding='UTF-8'?>
<project>
  <description>Analyze unknown survey HTML and generate parser extensions</description>
  <keepDependencies>false</keepDependencies>
  <properties>
    <hudson.model.ParametersDefinitionProperty>
      <parameterDefinitions>
        <hudson.model.StringParameterDefinition>
          <name>HTML_FILE</name>
          <defaultValue>{html_file}</defaultValue>
          <description>Path to HTML file to analyze</description>
        </hudson.model.StringParameterDefinition>
        <hudson.model.StringParameterDefinition>
          <name>WORK_ORDER_ID</name>
          <defaultValue>{work_order_id}</defaultValue>
          <description>Work order ID to update on completion</description>
        </hudson.model.StringParameterDefinition>
      </parameterDefinitions>
    </hudson.model.ParametersDefinitionProperty>
  </properties>
  <builders>
    <hudson.tasks.Shell>
      <command>
#!/bin/bash
set -e

# Install dependencies if needed
pip install beautifulsoup4 2>/dev/null || true

# Create analysis script
cat &gt; /tmp/analyze.py &lt;&lt; \'ANALYZE_EOF\'
import sys
import json
from pathlib import Path

sys.path.insert(0, "/home/dduckbeagy/survey_dd")

try:
    from bs4 import BeautifulSoup
    from survey_auto.self_improve.generator import extend_parser
    
    html_file = sys.argv[1]
    wo_id = sys.argv[2]
    
    html = Path(html_file).read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    
    patterns = []
    
    # Detect dropdowns
    for sel in soup.find_all("select"):
        name = sel.get("name", "")
        if not name: continue
        opts = [{"value": o.get("value",""), "label": o.get_text(strip=True)} 
                for o in sel.find_all("option") if o.get("value")]
        if opts:
            patterns.append({"type": "select", "variable": name, "options": opts, "text_inputs": []})
    
    # Detect text inputs
    for inp in soup.find_all("input", type=lambda t: t and t.lower() not in ("radio","checkbox","hidden","submit","button")):
        name = inp.get("name", "")
        if name:
            patterns.append({"type": "open", "variable": name, "options": [],
                            "text_inputs": [{"name": name, "label": "", "must": False, "input_type": inp.get("type","text")}]})
    
    # Detect rank widgets
    for ul in soup.select(\'[class*="rank"], [class*="Rank"], ul[data-rank]\'):
        items = ul.find_all("li")
        if len(items) >= 2:
            name = ul.get("data-name", ul.get("id", "rank"))
            opts = [{"value": li.get("data-value", li.get_text(strip=True)[:20]), 
                     "label": li.get_text(strip=True)} for li in items]
            if opts:
                patterns.append({"type": "rank", "variable": name, "options": opts, "text_inputs": []})
    
    # Generate extensions
    if patterns:
        success = extend_parser(patterns)
        result = {"success": success, "patterns_found": len(patterns), 
                  "patterns": [{"type": p["type"], "variable": p["variable"]} for p in patterns]}
    else:
        result = {"success": False, "patterns_found": 0, "error": "No patterns detected"}
    
    # Update work order
    wo_path = Path("/home/dduckbeagy/survey_dd/.omo/work_orders") / f"{wo_id}.json"
    if wo_path.exists():
        data = json.loads(wo_path.read_text())
        data["status"] = "completed" if result["success"] else "failed"
        data["result"] = result
        wo_path.write_text(json.dumps(data, indent=2))
    
    print(json.dumps(result))

except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
    sys.exit(1)
ANALYZE_EOF

python3 /tmp/analyze.py "${HTML_FILE}" "${WORK_ORDER_ID}"
      </command>
    </hudson.tasks.Shell>
  </builders>
  <publishers/>
  <buildWrappers/>
</project>'''


def _upload_job_config(job_name: str, config: str) -> bool:
    """Upload job configuration to Jenkins."""
    try:
        # Create job directory
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "mkdir", "-p", f"/var/jenkins_home/jobs/{job_name}"],
            capture_output=True, text=True, timeout=10
        )
        
        # Write config via docker exec
        cmd = f'echo \'{config}\' > /var/jenkins_home/jobs/{job_name}/config.xml'
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=10
        )
        
        return result.returncode == 0
    except Exception as e:
        logger.error("Failed to upload job config: %s", e)
        return False


def _run_job(job_name: str, **params) -> bool:
    """Trigger Jenkins job and wait for completion."""
    try:
        # Build job via REST API
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{JENKINS_URL}/job/{job_name}/buildWithParameters?{param_str}"
        
        # Use docker exec to trigger via curl
        cmd = f'curl -s -X POST "{url}" -u {JENKINS_USER}:'
        result = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            logger.error("Failed to trigger job: %s", result.stderr)
            return False
        
        # Wait for job to complete
        return _wait_for_job(job_name, timeout=120)
        
    except Exception as e:
        logger.error("Job execution failed: %s", e)
        return False


def _wait_for_job(job_name: str, timeout: int = 120) -> bool:
    """Wait for Jenkins job to complete."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            # Check last build status
            cmd = f'curl -s "{JENKINS_URL}/job/{job_name}/lastBuild/api/json"'
            result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "bash", "-c", cmd],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if not data.get("building", False):
                    result = data.get("result") == "SUCCESS"
                    logger.info("Job %s finished: %s", job_name, "SUCCESS" if result else "FAILED")
                    return result
            
            time.sleep(5)
        except Exception as e:
            logger.warning("Error checking job status: %s", e)
            time.sleep(5)
    
    logger.error("Job %s timed out after %ds", job_name, timeout)
    return False
