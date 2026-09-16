import re

with open("src/web/templates/index.html", "r") as f:
    html = f.read()

# 1. Update viewJobSteps
old_viewJobSteps = """  function viewJobSteps(jobId) {
    window._currentStepJobId = jobId;
    document.querySelectorAll('.stepJobSelect').forEach(sel => sel.value = jobId);
    switchTab('tab-step1');
  }"""

new_viewJobSteps = """  function viewJobSteps(jobId) {
    window._currentStepJobId = jobId;
    document.getElementById('jobsListCard').style.display = 'none';
    document.getElementById('jobDetailContainer').style.display = 'block';
    document.getElementById('detailJobIdText').innerText = jobId;
    
    // Move the step panes into the detail area if not already there
    const stepsArea = document.getElementById('jobDetailStepsArea');
    ['tab-step1', 'tab-step2', 'tab-step3', 'tab-step4', 'tab-step5'].forEach(id => {
      const el = document.getElementById(id);
      if (el && el.parentNode !== stepsArea) {
        stepsArea.appendChild(el);
      }
    });
    
    // Hide all step panes initially
    document.querySelectorAll('.job-step-pane').forEach(el => el.style.display = 'none');
    
    loadStepsData(jobId);
    switchJobStepTab('tab-step1');
  }
  
  function closeJobDetails() {
    document.getElementById('jobsListCard').style.display = 'block';
    document.getElementById('jobDetailContainer').style.display = 'none';
  }
  
  function switchJobStepTab(tabId) {
    // hide all job-step-panes
    ['tab-step1', 'tab-step2', 'tab-step3', 'tab-step4', 'tab-step5'].forEach(id => {
      const el = document.getElementById(id);
      if(el) el.style.display = 'none';
    });
    // show active
    const activeEl = document.getElementById(tabId);
    if(activeEl) activeEl.style.display = 'block';
    
    // update buttons
    ['btn-tab-step1', 'btn-tab-step2', 'btn-tab-step3', 'btn-tab-step4', 'btn-tab-step5'].forEach(id => {
      const el = document.getElementById(id);
      if(el) {
        if(id === 'btn-' + tabId) el.classList.add('active');
        else el.classList.remove('active');
      }
    });
  }"""
html = html.replace(old_viewJobSteps, new_viewJobSteps)

# 2. Add class="job-step-pane" to the tab-step panes and remove their "tab-pane" class so they aren't controlled by global switchTab
for i in range(1, 6):
    html = html.replace(f'<div id="tab-step{i}" class="tab-pane">', f'<div id="tab-step{i}" class="job-step-pane" style="display:none;">')
    html = html.replace(f'<div id="tab-step{i}" class="tab-pane active">', f'<div id="tab-step{i}" class="job-step-pane" style="display:none;">')

# 3. Remove .stepJobSelect completely from DOM
html = re.sub(r'<div style="display:flex;align-items:center;gap:10px;">\s*<span style="font-size:13px;color:var\(--text-sub\);font-weight:600;">Chiến dịch đang xem:</span>\s*<select class="form-control stepJobSelect".*?</select>\s*</div>', '', html, flags=re.DOTALL)

with open("src/web/templates/index.html", "w") as f:
    f.write(html)
print("Rewrite OK")
