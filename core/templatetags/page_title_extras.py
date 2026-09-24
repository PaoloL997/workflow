from django import template

from core.page_title import format_commessa_page_title

register = template.Library()


@register.simple_tag(name="commessa_title")
def commessa_title(testata, section=""):
    """Page title of a commessa page: the job number, not the word "Commessa"."""
    if testata is None:
        job = ""
    elif isinstance(testata, dict):
        job = testata.get("job", "")
    else:
        job = getattr(testata, "job", testata)
    return format_commessa_page_title(job, section)
