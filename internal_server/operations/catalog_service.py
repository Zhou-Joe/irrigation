"""Team-owned catalogue versions; submitted work always keeps its issued wording."""
import uuid

from django.db import transaction
from django.db.models import Q, F

from .models import ReferenceCatalog, ReferenceNode, Team


def current_catalog(team):
    if team.work_catalog_id:
        return ReferenceCatalog.objects.filter(pk=team.work_catalog_id, business=team.business).filter(
            Q(owner_team=team) | Q(owner_team__isnull=True)).first()
    return ReferenceCatalog.objects.filter(business=team.business, owner_team__isnull=True).order_by('-imported_at', '-pk').first()


def selectable_catalogs(team):
    return ReferenceCatalog.objects.filter(business=team.business).filter(Q(owner_team=team) | Q(owner_team__isnull=True))


def node_rows(catalog):
    return [{'id':n.pk, 'parent':n.parent_id, 'label':n.label, 'kind':n.kind, 'order':n.order}
            for n in catalog.nodes.all()] if catalog else []


def selection_snapshot(catalog, identifiers):
    ids = {int(value) for value in identifiers}
    if not ids or len(ids) > 300:
        raise ValueError('请选择工作内容。')
    nodes = {n.pk:n for n in catalog.nodes.all()}
    branches = {n.parent_id for n in nodes.values() if n.parent_id}
    if not ids.issubset(nodes) or ids.intersection(branches):
        raise ValueError('请选择当前目录中的末级工作内容。')
    result = []
    for identifier in sorted(ids, key=lambda key:nodes[key].order):
        node = nodes[identifier]; path = []; visited = set()
        while node:
            if node.pk in visited:raise ValueError('工作目录层级存在循环。')
            visited.add(node.pk);path.insert(0,node.label);node=nodes.get(node.parent_id)
        result.append({'node_id':identifier,'path':path,'kind':nodes[identifier].kind})
    return result


class CatalogConflict(ValueError):
    pass


@transaction.atomic
def revise_catalog(team, expected_version, action, identifier=None, **values):
    # Each edit publishes a separate version. Neither another team's choices nor
    # any old form, execution record or issued task is rewritten by maintenance.
    Team.objects.filter(pk=team.pk).update(work_catalog_id=F('work_catalog_id'))
    team=Team.objects.select_related('business','work_catalog').get(pk=team.pk)
    original=current_catalog(team)
    if str(original.pk if original else '') != str(expected_version):
        raise CatalogConflict('工作目录已有更新，请重新加载后再保存。')
    rows=node_rows(original);by_id={str(row['id']):row for row in rows}
    item=by_id.get(str(identifier))
    if action not in ('add','edit','delete'):raise ValueError('操作无效。')
    if action!='add' and not item:raise ValueError('请选择要维护的工作条目。')
    if action=='delete':
        if any(str(row['parent'])==str(identifier) for row in rows):
            raise ValueError('请先移除子条目，避免意外删除整个工作分支。')
        rows.remove(item)
    else:
        label=str(values.get('label','')).strip();parent=str(values.get('parent','') or '')
        kind=values.get('kind','node')
        if not label or len(label)>255:raise ValueError('条目名称应为 1–255 个字符。')
        if kind not in ('node','note'):raise ValueError('条目类型无效。')
        if parent and parent not in by_id:raise ValueError('上级条目不存在。')
        if item and parent==str(identifier):raise ValueError('条目不能成为自己的上级。')
        cursor=parent;visited={str(identifier)} if item else set()
        while cursor:
            if cursor in visited:raise ValueError('条目层级不能形成循环。')
            visited.add(cursor);cursor=str(by_id[cursor]['parent'] or '')
            if len(visited)>20:raise ValueError('工作目录最多支持 20 层，请整理后再保存。')
        order=int(values.get('order',len(rows)))
        if not 0<=order<=100000:raise ValueError('排序应在 0–100000 之间。')
        if not item:
            item={'id':'new'};rows.append(item)
        item.update(parent=int(parent) if parent else None,label=label,kind=kind,order=order)
    if len(rows)>2000:raise ValueError('工作目录最多支持 2000 个条目。')
    version=ReferenceCatalog.objects.create(business=team.business,owner_team=team,
        name='植保作业目录',version=uuid.uuid4().hex,source_name='业务数据维护')
    mapping={};pending=list(sorted(rows,key=lambda row:row['order']))
    while pending:
        ready=[row for row in pending if not row['parent'] or str(row['parent']) in mapping]
        if not ready:raise ValueError('工作目录中有无效的父子关系。')
        nodes=[ReferenceNode(catalog=version,parent=mapping.get(str(row['parent'])),label=row['label'],
            kind=row['kind'],source_line=rows.index(row)+1,order=row['order']) for row in ready]
        ReferenceNode.objects.bulk_create(nodes)
        for row,node in zip(ready,nodes):mapping[str(row['id'])]=node;pending.remove(row)
    team.work_catalog=version;team.save(update_fields=['work_catalog'])
    selected=mapping.get(str(identifier)) if action=='edit' else mapping.get('new') if action=='add' else None
    return version,selected.pk if selected else None
