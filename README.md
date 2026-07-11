# RepoFlow: GitHub Repository Security & Structure Intelligence

🚀 **Live Demo:** [repoflow-1j5f.onrender.com](https://repoflow-1j5f.onrender.com/)

There are thousands of repositories out there, but GitHub only shows you the code. It doesn't tell you whether a project is secure, actively maintained, or where a beginner should even start contributing.

**RepoFlow** is a security-first repository intelligence platform designed to bring all of this together into one comprehensive report. 

To make the analysis reliable, RepoFlow integrates **OpenSSF (Open Source Security Foundation)** projects instead of relying only on custom heuristics. OpenSSF is a Linux Foundation initiative backed by organizations like Google, Microsoft, GitHub, and many others, developing security tools to improve the safety of open-source software.

---

## Key Features

### 🛡️ OpenSSF Security Scorecard
Evaluates a project against **18 standard security heuristics** to analyze and present a clear breakdown of supply-chain risk:
- **Critical Checks:** Branch Protection, Pinned Dependencies, Token Permissions, and SAST.
- **Development Health:** CI-Tests, Contributors, Dependency-Update-Tool, Fuzzing, and Vulnerabilities.
- **Release Discipline:** Signed-Releases, Packaging, Binary-Artifacts, and Code-Review.

### 🔍 OSV Vulnerability Scanner
Directly queries the **Open Source Vulnerability (OSV)** database using the repository's default branch commit SHA. It locates known package and dependency vulnerabilities to alert developers before integrating dependencies or onboarding.

### 🏅 OpenSSF Best Practices Badge
Detects and displays the repository's official **OpenSSF Best Practices Badge** (Passing, Silver, or Gold) directly from the database, demonstrating the project's adherence to professional open-source standards.

### 🤖 Multi-Agent CrewAI Analysis
Orchestrates AI agents using a sequential model to analyze repository characteristics:
1. **Security Agent:** Analyzes security metrics, branch protection rules, and package vulnerability scans to generate a plain-English security posture report.
2. **Structure Agent:** Reviews tech stack framework elements, dependency profiles, and key directory purposes.
*(Note: Issue and PR analysis agents have been removed from the workflow).*

### 📄 Premium PDF Export
Generates print-friendly, beautifully structured PDF copies of any security report using the **Browserless API**, removing local headless Chromium and Playwright compilation requirements.

---

## Platform Architecture

```
                                  +-------------------+
                                  |    Web Browser    |
                                  +---------+---------+
                                            |
                                            v
                                  +---------+---------+
                                  | Django Controllers |
                                  +---------+---------+
                                            |
                         +------------------+------------------+
                         |                                     |
                         v                                     v
             +-----------+-----------+             +-----------+-----------+
             |  CrewAI Orchestration |             |  Deterministic APIs   |
             +-----------+-----------+             +-----------+-----------+
                         |                                     |
             +-----------+-----------+                         +-----------+
             |                       |                                     |
             v                       v                                     v
       +-----+-----+           +-----+-----+                         +-----+-----+
       | Security  |           | Structure |                         | OpenSSF   |
       |  Agent    |           |  Agent    |                         | Scorecard |
       +-----------+           +-----------+                         +-----+-----+
                                                                           |
                                                                           v
                                                                     +-----+-----+
                                                                     |  OSV /    |
                                                                     |  Badges   |
                                                                     +-----------+
```

### Flow Breakdown:
1. **Request Ingestion:** The user submits a public GitHub URL on the responsive frontend dashboard.
2. **Deterministic Data Collection:** RepoFlow calls the GitHub REST API, the OpenSSF Scorecard Dev API, OSV Vulnerability database, and the Best Practices registry to build a comprehensive repository snapshot.
3. **Agent Orchestration:** The CrewAI workflow executes. The specialized agents use tool-wrapped functions to review the repository snapshot, ensuring that the final narrative is strictly grounded in real metrics (no hallucinations).
4. **Report Rendering:** The rules-based health metrics are combined with AI-generated markdown reports, converted into safe HTML, and served to the user with instant PDF download capabilities.

---

## 🛠️ Tech Stack & Tooling

- **Core Framework:** Python & Django
- **Agent Orchestration:** CrewAI (Sequential Workflow)
- **Language Models (LLMs):** Groq (Llama 3.1)
- **Security & Metadata APIs:** GitHub REST API, OpenSSF Scorecard Dev API, OSV.dev API, OpenSSF Best Practices registry.
- **PDF Export:** Browserless API (Chrome-as-a-service)
- **Hosting & Deployment:** Render

---

## 💡 Engineering Insights & Lessons Learned

While building RepoFlow, several key backend and software engineering concepts were put to the test:
- **Deterministic Python vs. LLM:** Knowing when rule-based Python logic is a cleaner, faster, and more reliable engineering choice than an LLM for parsing structured security metadata.
- **Integrating Open-Source Security Tools:** Learning to interface with and normalize responses from industry-standard security foundations (OpenSSF, OSV) in a real-world Django platform.
- **Modern Repository Assessment:** Gaining a deeper understanding of how modern open-source software is evaluated for production readiness beyond simply skimming the source code.
