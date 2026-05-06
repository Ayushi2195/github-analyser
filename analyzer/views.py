import markdown
from django.shortcuts import render
from .crew.crew import run_analysis

def index(request):
    return render(request, 'analyzer/index.html')

def analyze(request):
    if request.method == 'POST':
        repo_url = request.POST.get('repo_url', '').strip()
        try:
            md_report = run_analysis(repo_url)
            html_report = markdown.markdown(md_report, extensions=['tables', 'fenced_code'])
            return render(request, 'analyzer/index.html', {
                'report': html_report,
                'repo_url': repo_url
            })
        except Exception as e:
            return render(request, 'analyzer/index.html', {
                'error': str(e),
                'repo_url': repo_url
            })
    return render(request, 'analyzer/index.html')