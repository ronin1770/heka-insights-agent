## 📏 File, Class, and Metadata Standards

To maintain consistency, readability, and traceability across the project, all contributors must follow the standards below.

---

### 📁 File Naming Convention

* Use **snake_case** for all filenames
* Names should clearly reflect purpose
* Avoid abbreviations unless widely understood

**Examples:**

```text
metrics_collector.py
openmetrics_formatter.py
json_formatter.py
data_sender.py
config_loader.py
```

---

### 🧱 Class Naming Convention

* Use **PascalCase** for class names
* Class name should match responsibility
* Prefer one primary class per file

**Examples:**

```python
class MetricsCollector:
class OpenMetricsFormatter:
class JsonFormatter:
class DataSender:
```

---

### 📝 Required File Header

Each Python file must include a header block at the top:

```python
"""
File: <filename>
Description: <short description of what this file does>
Author: <your name or organization>
Dev Started On: <YYYY-MM-DD>
Epic / Related Story: <EPIC-ID or GitHub Issue #>
"""
```

**Example:**

```python
"""
File: metrics_collector.py
Description: Collects CPU, memory, disk I/O, and network I/O metrics from Linux systems.
Author: FAMRO LLC
Dev Started On: 2026-04-01
Epic / Related Story: #12
"""
```

---

### 🧾 Class Docstring Standard

Each main class should include a docstring describing its purpose and linkage:

```python
class MetricsCollector:
    """
    Description: Collects core system metrics at defined intervals.
    Epic / Related Story: #12
    """
```

---

### 🔗 Epic / Story Referencing

* Use **GitHub issue numbers** as the primary reference
* Format: `#<issue_number>`
* For larger work, reference Epic issue

**Examples:**

```text
#12
#45
```

---

### 📌 General Guidelines

* Keep files **single responsibility focused**
* Avoid large multi-purpose files
* Keep descriptions **short, factual, and clear**
* Update metadata if file ownership or scope changes
* Do not leave placeholder metadata in committed code

---

### ✅ Pull Request Checklist (Required)

Before submitting a PR, ensure:

* [ ] File naming follows conventions
* [ ] Class naming follows conventions
* [ ] File header is present and correct
* [ ] Class docstrings are added
* [ ] Epic / Issue reference is included

---

### ⚠️ Notes

* Contributions that do not follow these standards may be requested for revision
* These standards are designed to keep the telemetry agent **simple, maintainable, and production-ready**
