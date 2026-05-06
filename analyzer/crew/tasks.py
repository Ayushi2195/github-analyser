from crewai import Task

def repo_structure_task(agent, repo_url):
    return Task(
        description=f"Analyze the structure of this repository: {repo_url}. List top-level files/folders and describe the project layout.",
        expected_output="Markdown report of repository structure with descriptions of key files and folders.",
        agent=agent
    )

def issue_task(agent, repo_url):
    return Task(
        description=f"List and summarize all open issues in: {repo_url}. Group by type if possible.",
        expected_output="Markdown report of open issues with titles, labels, and brief summaries.",
        agent=agent
    )

def pr_task(agent, repo_url):
    return Task(
        description=f"Review open pull requests in: {repo_url}. Summarize what changes are pending.",
        expected_output="Markdown report of open PRs with titles, authors, and what they change.",
        agent=agent
    )

def branch_task(agent, repo_url):
    return Task(
        description=f"List all active branches in: {repo_url}. Identify the main branch and feature/release branches.",
        expected_output="Markdown report of branches and their likely purpose.",
        agent=agent
    )