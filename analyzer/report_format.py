"""
Shared report section templates — keeps agent outputs consistent and detailed.
"""

STRUCTURE_FORMAT = """
Write ONLY the body (no main title). Use this exact structure:

## Repository Structure Analysis

### Project Overview
Write 2-4 sentences about purpose, maturity, and what the root layout suggests.

### Tech Stack
Bullet list of languages, frameworks, and dependency files (cite actual file names from data).

### Key Files and Folders
For EACH root file/folder, one bullet in this form:
- **name** (file|dir): 1-2 sentences on likely purpose.

### Repository Stats
Bullet list with exact numbers from metadata:
- **Stars:** N
- **Forks:** N
- **Default branch:** name
- **Open issues (total):** N
- **Primary language:** X
- **License:** X or "Not specified"
- **Topics:** list or "None — consider adding topics for discoverability"
- **Last updated:** date if available
"""

ISSUES_FORMAT = """
Write ONLY the body (no main title). Use this exact structure:

## Open Issues Report

Opening line: "There are currently N open issues on GitHub." (use exact count)

Group ALL issues by label theme. For each group use ### Group Name
Under each group, one bullet per issue:
- **Issue #{number}:** {title} — reported by @{author} — [View issue]({url})

If an issue has no labels, put under ### Uncategorized
If zero issues: say so clearly.

Rules:
- Mention EVERY issue from the data (do not skip any).
- Use real @author logins and issue numbers from JSON.
- Use the exact issue URLs provided in the data.
- NEVER make general statements such as "large issue volume is normal".
- If a field is missing, write "Data unavailable" instead of guessing.
"""

PRS_FORMAT = """
Write ONLY the body (no main title). Use this exact structure:

## Pull Request Analysis Report

### Introduction
1-2 sentences on overall PR activity.

### Open Pull Requests
If any PRs exist, one bullet each:
- **PR #{number}:** "{title}" — submitted by @{author}, **{head}** → **{base}** — [View PR]({url})
  - 1 sentence on likely intent based on title/branches.

### Conclusion
Summarize count and what it means for the project (review backlog, active development, etc.).
If zero PRs: state that clearly.
Rules:
- Use only the PR JSON provided.
- NEVER make general statements such as "PR activity is high".
- If a field is missing, write "Data unavailable" instead of guessing.
"""

BRANCHES_FORMAT = """
Write ONLY the body (no main title). Use this exact structure:

## Branches

### Real Numbers Summary
State default branch, sampled branch count, protected branch count, and PR target counts.

### Branch Categories
Group branches by meaning inferred from exact branch names:
- Dependabot updates
- Copilot suggestions
- CI/CD work
- Feature branches
- Bug fixes
- Documentation
- Release branches
- Other branches

For each group, show count and 1-3 exact example branch names.

### Most Interesting Non-Automated Branches
List only the top 5 non-automated branches. For each branch, infer purpose from the branch name.
Examples:
- fix-memory-saving -> Bug fix targeting memory optimization
- ci/split-e2e-ai-tests -> CI/CD pipeline work splitting the E2E test suite
- feature/user-auth -> Feature work for user authentication

### Protected Branches
List branches where protected=true, or state none are protected.

Rules:
- Use exact branch names from JSON.
- NEVER write generic filler like "likely used for feature or topic development".
- Dependabot and Copilot branches are automated; group them instead of describing every one.
- If data is missing, say "Data unavailable".
"""
