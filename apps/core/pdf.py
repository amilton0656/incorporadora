import io
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa


def render_to_pdf(template_name, context, filename='documento.pdf'):
    template = get_template(template_name)
    html = template.render(context)
    buffer = io.BytesIO()
    pisa.pisaDocument(io.BytesIO(html.encode('UTF-8')), buffer)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
