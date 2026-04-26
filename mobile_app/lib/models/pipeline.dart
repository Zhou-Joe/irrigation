class Pipeline {
  final int id;
  final String name;
  final String code;
  final String description;
  final String pipelineType;
  final String pipelineTypeDisplay;
  final List<dynamic> linePoints;
  final String lineColor;
  final int lineWeight;

  Pipeline({
    required this.id,
    required this.name,
    required this.code,
    this.description = '',
    required this.pipelineType,
    required this.pipelineTypeDisplay,
    this.linePoints = const [],
    this.lineColor = '#CC3333',
    this.lineWeight = 3,
  });

  factory Pipeline.fromJson(Map<String, dynamic> json) {
    return Pipeline(
      id: json['id'] is int ? json['id'] : (json['id'] as num?)?.toInt() ?? 0,
      name: json['name']?.toString() ?? '',
      code: json['code']?.toString() ?? '',
      description: json['description']?.toString() ?? '',
      pipelineType: json['pipeline_type']?.toString() ?? 'irrigation',
      pipelineTypeDisplay: json['pipeline_type_display']?.toString() ?? '灌溉水管',
      linePoints: json['line_points'] ?? [],
      lineColor: json['line_color']?.toString() ?? '#CC3333',
      lineWeight: json['line_weight'] is int
          ? json['line_weight']
          : (json['line_weight'] as num?)?.toInt() ?? 3,
    );
  }
}
