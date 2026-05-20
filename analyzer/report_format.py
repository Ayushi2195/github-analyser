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
"""

BRANCHES_FORMAT = """
Write ONLY the body (no main title). Use this exact structure:

## Branches

### Main Branch
State the default branch name and its role.

### Feature Branches
List non-default branches that look like features (prefixes: feat, feature, dev, soda, mcp, etc.).
Bullet each: **branch_name** — brief guess of purpose from name.

### Release Branches
List release/* or version-like branches, or state "No explicit release branches identified."

### Protected Branches
List branches where protected=true, or state none are protected and recommend protecting main.

End with 1-2 sentences of workflow recommendation.
"""
