from django.core.paginator import Paginator


def page_slice(request, queryset, key='page', label='', size=30):
    page = Paginator(queryset, size).get_page(request.GET.get(key, 1))
    def url(number):
        params = request.GET.copy()
        params[key] = number
        return '?' + params.urlencode()
    return page, {'label':label, 'page':page,
        'previous':url(page.previous_page_number()) if page.has_previous() else '',
        'next':url(page.next_page_number()) if page.has_next() else ''}
