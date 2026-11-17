import re

from django import forms
from .models import Location
from .work_parameters import definitions, location_definitions, DEFAULT_DIRECTIONS, IMPACT_DIRECTION


class LocationForm(forms.ModelForm):
    orientation_options = forms.CharField(label='建筑方位', required=False, max_length=21000,
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': '东、南、西、北', 'aria-describedby': 'buildingOrientationHelp'}))

    class Meta:
        model = Location
        fields = ['name', 'code', 'kind', 'map_display', 'parent', 'description', 'latitude', 'longitude', 'parameters']
        labels = {'name': '地点名称', 'code': '地点编号（选填）', 'kind': '地点类型', 'parent': '上级地点（选填）',
                  'map_display': '地图显示方式', 'description': '位置说明',
                  'latitude': '纬度（选填）', 'longitude': '经度（选填）', 'parameters': '地点填报参数（JSON 配置）'}
        help_texts = {'kind': '图钉的图标和颜色按地点类型区分。',
                      'map_display': '建筑等地点可在下方地图点选；诱捕笼和蜂箱使用专用图钉。未定位的地点仍可用于工单。'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3}), 'parameters': forms.Textarea(attrs={'rows': 5, 'spellcheck':'false'})}

    def __init__(self, *args, parents, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['map_display'].required = False
        self.fields['parent'].queryset = parents
        self.fields['parent'].label_from_instance = lambda obj: obj.name
        self.orientation_field = next((field for field in location_definitions(self.instance, available_locations=parents)
                          if field['key'] == IMPACT_DIRECTION and field['type'] == 'choice'), None)
        options = self.orientation_field['options'] if self.orientation_field else DEFAULT_DIRECTIONS
        self.initial['orientation_options'] = '\n'.join(option['label'] for option in options)
        if self.instance.legacy_zone_id:
            self.fields['latitude'].disabled = True
            self.fields['longitude'].disabled = True

    def clean_map_display(self):
        if self.cleaned_data.get('kind') in Location.POINT_KINDS:
            return 'pin'
        return self.cleaned_data.get('map_display') or self.instance.map_display or 'auto'

    def clean_parameters(self):
        # Map creation and older clients may omit this administrative field.
        if self.is_bound and 'parameters' not in self.data:
            return self.instance.parameters
        try:
            return definitions(self.cleaned_data.get('parameters'), allow_location=False)
        except ValueError as error:
            raise forms.ValidationError(str(error)) from error

    def clean_orientation_options(self):
        return self.cleaned_data['orientation_options'].replace('\r\n', '\n').replace('\r', '\n')

    def clean(self):
        data = super().clean()
        if (data.get('kind') == 'building' and 'orientation_options' in data and 'orientation_options' in self.data
                and 'parameters' in data and data['orientation_options'] != self.initial['orientation_options'].strip()):
            known_labels = {option['label'] for option in (self.orientation_field or {}).get('options', [])}
            labels = []
            for line in data['orientation_options'].splitlines():
                line = line.strip()
                # Existing labels may themselves contain punctuation. Keeping
                # each rendered line intact lets users append a new direction.
                labels.extend([line] if line in known_labels else [
                    label.strip() for label in re.split(r'[、,，;；]+', line) if label.strip()])
            if not labels or len(labels) > 100 or any(len(label) > 200 for label in labels):
                self.add_error('orientation_options', '请填写 1–100 个建筑方位，每个不超过 200 字。')
            elif len(labels) != len(set(labels)):
                self.add_error('orientation_options', '建筑方位不能重复。')
            else:
                fields = data['parameters']
                previous = next((field for field in fields if field['key'] == IMPACT_DIRECTION), None)
                original = self.orientation_field or {}
                values = {option['label']: option['value'] for option in [
                    *DEFAULT_DIRECTIONS, *original.get('options', []), *(previous or {}).get('options', [])]}
                direction = {key: value for key, value in (previous or original).items() if not key.startswith('owner_')}
                direction.update(key=IMPACT_DIRECTION, label=direction.get('label', '撞击方向'), type='choice',
                                 options=[{'value': values.get(label, label), 'label': label} for label in labels])
                try:
                    data['parameters'] = definitions([field for field in fields if field['key'] != IMPACT_DIRECTION] + [direction], allow_location=False)
                except ValueError as error:
                    self.add_error('orientation_options', str(error))
        if self.instance.legacy_zone_id and (data.get('latitude') is not None or data.get('longitude') is not None):
            raise forms.ValidationError('共享的灌溉区域直接使用原区域边界。')
        return data
