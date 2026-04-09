const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "Irrigation Management Team";
pres.title = "灌溉管理系统解决方案";

// Color palette - water/nature theme
const C = {
  navy: "0F2027",
  deepBlue: "1A3A4A",
  teal: "028090",
  seafoam: "00A896",
  mint: "02C39A",
  green: "2C5F2D",
  moss: "97BC62",
  lightGreen: "D4E8C2",
  white: "FFFFFF",
  offWhite: "F7F9FC",
  lightGray: "E8ECF1",
  gray: "94A3B8",
  darkGray: "334155",
  coral: "F96167",
  gold: "F9E795",
};

// Reusable shadow factory
const cardShadow = () => ({ type: "outer", blur: 8, offset: 3, angle: 135, color: "000000", opacity: 0.12 });

// ──────────────────────────────────────────────────────────────────
// SLIDE 1: Title
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.navy };

  // Decorative top bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.08, fill: { color: C.mint }
  });

  // Subtitle area
  slide.addText("Irrigation Management System", {
    x: 0.8, y: 1.2, w: 8.4, h: 0.5,
    fontSize: 14, fontFace: "Calibri", color: C.seafoam,
    align: "left", charSpacing: 8, bold: true
  });

  // Main title
  slide.addText("灌溉管理系统\n解决方案", {
    x: 0.8, y: 1.7, w: 8.4, h: 2.0,
    fontSize: 44, fontFace: "Arial Black", color: C.white,
    align: "left", lineSpacingMultiple: 1.2
  });

  // Decorative line
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.9, w: 1.5, h: 0.05, fill: { color: C.mint }
  });

  // Description
  slide.addText("一站式灌溉数据管理 · 移动端地图应用 · 自动数据同步", {
    x: 0.8, y: 4.1, w: 8, h: 0.5,
    fontSize: 16, fontFace: "Calibri", color: C.gray
  });

  // Date
  slide.addText("2026年4月", {
    x: 0.8, y: 4.8, w: 3, h: 0.4,
    fontSize: 14, fontFace: "Calibri", color: C.gray
  });
}

// ──────────────────────────────────────────────────────────────────
// SLIDE 2: System Architecture Overview
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  // Title bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.deepBlue }
  });
  slide.addText("系统架构总览", {
    x: 0.6, y: 0.15, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Arial Black", color: C.white, margin: 0
  });

  // Three columns: Maxicom -> Django -> Flutter
  const cols = [
    { title: "Maxicom² 数据库", sub: "数据来源", color: C.teal, icon: "🗄️",
      items: ["Access 数据库", "灌溉控制数据", "天气 / 流量 / ET", "电磁阀运行记录"] },
    { title: "Django 管理平台", sub: "数据处理与展示", color: C.seafoam, icon: "🖥️",
      items: ["PostgreSQL 数据库", "数据可视化大屏", "用户权限管理", "灌溉区域标注"] },
    { title: "Flutter 手机应用", sub: "现场移动办公", color: C.mint, icon: "📱",
      items: ["交互式灌溉地图", "区域信息查看", "维修记录上传", "实时数据同步"] },
  ];

  cols.forEach((col, i) => {
    const x = 0.5 + i * 3.1;

    // Card background
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.2, w: 2.8, h: 3.8,
      fill: { color: C.white }, shadow: cardShadow()
    });

    // Top accent bar
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 1.2, w: 2.8, h: 0.08, fill: { color: col.color }
    });

    // Icon
    slide.addText(col.icon, {
      x: x, y: 1.4, w: 2.8, h: 0.6,
      fontSize: 28, align: "center"
    });

    // Card title
    slide.addText(col.title, {
      x: x + 0.2, y: 2.0, w: 2.4, h: 0.4,
      fontSize: 15, fontFace: "Arial", color: C.darkGray, bold: true, align: "center"
    });

    // Subtitle
    slide.addText(col.sub, {
      x: x + 0.2, y: 2.35, w: 2.4, h: 0.3,
      fontSize: 11, fontFace: "Calibri", color: col.color, align: "center"
    });

    // Separator
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.8, y: 2.7, w: 1.2, h: 0.02, fill: { color: C.lightGray }
    });

    // Bullet items
    const items = col.items.map((item, idx) => ({
      text: item,
      options: {
        bullet: true, breakLine: idx < col.items.length - 1,
        fontSize: 12, fontFace: "Calibri", color: C.darkGray,
        paraSpaceAfter: 6
      }
    }));
    slide.addText(items, {
      x: x + 0.3, y: 2.85, w: 2.2, h: 2.0
    });
  });

  // Arrows between columns
  slide.addText("→", {
    x: 3.15, y: 2.6, w: 0.6, h: 0.5,
    fontSize: 24, color: C.seafoam, align: "center", bold: true
  });
  slide.addText("→", {
    x: 6.25, y: 2.6, w: 0.6, h: 0.5,
    fontSize: 24, color: C.mint, align: "center", bold: true
  });
}

// ──────────────────────────────────────────────────────────────────
// SLIDE 3: Django Platform Detail
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.deepBlue }
  });
  slide.addText("数据管理平台 — Django", {
    x: 0.6, y: 0.15, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Arial Black", color: C.white, margin: 0
  });

  // Left side: 4 feature cards in 2x2 grid
  const features = [
    { title: "数据存储", desc: "PostgreSQL 数据库\n存储所有灌溉历史数据\n支持百万级数据量", color: C.teal },
    { title: "数据可视化", desc: "仪表盘大屏展示\n流量 / ET / 降雨图表\n实时数据更新", color: C.seafoam },
    { title: "用户管理", desc: "管理员 / 主管 / 工人\n分级权限控制\n操作审计日志", color: C.mint },
    { title: "区域标注", desc: "地图上标记灌溉区域\nZone 编号与命名\n区域与站点关联", color: C.moss },
  ];

  features.forEach((feat, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 2.6;
    const y = 1.2 + row * 2.0;

    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: y, w: 2.4, h: 1.8,
      fill: { color: C.white }, shadow: cardShadow()
    });

    // Accent bar left
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: y, w: 0.06, h: 1.8, fill: { color: feat.color }
    });

    slide.addText(feat.title, {
      x: x + 0.2, y: y + 0.1, w: 2.0, h: 0.35,
      fontSize: 15, fontFace: "Arial", color: feat.color, bold: true, margin: 0
    });

    slide.addText(feat.desc, {
      x: x + 0.2, y: y + 0.5, w: 2.0, h: 1.2,
      fontSize: 11, fontFace: "Calibri", color: C.darkGray, lineSpacingMultiple: 1.3
    });
  });

  // Right side: Data types summary
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.2, w: 3.8, h: 3.8,
    fill: { color: C.white }, shadow: cardShadow()
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.7, y: 1.2, w: 3.8, h: 0.08, fill: { color: C.teal }
  });

  slide.addText("数据类型一览", {
    x: 5.9, y: 1.4, w: 3.4, h: 0.4,
    fontSize: 16, fontFace: "Arial", color: C.darkGray, bold: true
  });

  const dataTypes = [
    { name: "天气数据", desc: "温度、湿度、ET、降雨量" },
    { name: "流量数据", desc: "各区域实时流量读数" },
    { name: "事件日志", desc: "报警、警告、错误记录" },
    { name: "运行时间", desc: "电磁阀开启时长统计" },
    { name: "ET蒸散量", desc: "土壤湿度与蒸散计算" },
    { name: "信号日志", desc: "控制器通讯状态" },
  ];

  dataTypes.forEach((dt, i) => {
    const y = 1.9 + i * 0.5;
    slide.addShape(pres.shapes.OVAL, {
      x: 6.0, y: y + 0.08, w: 0.18, h: 0.18,
      fill: { color: C.seafoam }
    });
    slide.addText(dt.name, {
      x: 6.3, y: y, w: 1.3, h: 0.35,
      fontSize: 12, fontFace: "Arial", color: C.darkGray, bold: true, margin: 0
    });
    slide.addText(dt.desc, {
      x: 7.5, y: y, w: 1.8, h: 0.35,
      fontSize: 11, fontFace: "Calibri", color: C.gray, margin: 0
    });
  });
}

// ──────────────────────────────────────────────────────────────────
// SLIDE 4: Flutter Mobile App
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.deepBlue }
  });
  slide.addText("移动端应用 — Flutter", {
    x: 0.6, y: 0.15, w: 8, h: 0.6,
    fontSize: 28, fontFace: "Arial Black", color: C.white, margin: 0
  });

  // Left: Phone mockup area
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.3, w: 2.5, h: 4.0,
    fill: { color: C.darkGray }, rectRadius: 0.15,
    shadow: cardShadow()
  });

  // Phone screen
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.75, y: 1.55, w: 2.2, h: 3.3,
    fill: { color: C.lightGray }, rectRadius: 0.05
  });

  // Map placeholder content
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.85, y: 1.7, w: 2.0, h: 1.8,
    fill: { color: C.teal, transparency: 15 }
  });

  // Simulated map zones
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 1.0, y: 2.0, w: 0.7, h: 0.5,
    fill: { color: C.mint, transparency: 30 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 1.8, y: 1.9, w: 0.9, h: 0.6,
    fill: { color: C.seafoam, transparency: 30 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 1.2, y: 2.6, w: 0.5, h: 0.7,
    fill: { color: C.moss, transparency: 30 }
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 1.9, y: 2.7, w: 0.6, h: 0.5,
    fill: { color: C.lightGreen, transparency: 30 }
  });

  // Zone label
  slide.addText("灌溉区域地图\n缩放 · 定位 · 选择", {
    x: 0.85, y: 3.55, w: 2.0, h: 0.6,
    fontSize: 10, fontFace: "Calibri", color: C.darkGray, align: "center",
    lineSpacingMultiple: 1.2
  });

  // Bottom nav placeholder
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.85, y: 4.3, w: 2.0, h: 0.4,
    fill: { color: C.white }
  });
  slide.addText("地图  |  记录  |  我的", {
    x: 0.85, y: 4.3, w: 2.0, h: 0.4,
    fontSize: 9, fontFace: "Calibri", color: C.teal, align: "center", valign: "middle"
  });

  // Right side: Feature descriptions
  const appFeatures = [
    { num: "01", title: "交互式灌溉地图", desc: "基于航拍图的交互式地图，支持缩放、定位、区域选择。不同颜色标注各灌溉区域，直观展示浇水状态。", color: C.teal },
    { num: "02", title: "区域信息实时同步", desc: "与Django平台实时同步区域数据，在地图上点击任意区域即可查看详细灌溉信息、运行状态和历史记录。", color: C.seafoam },
    { num: "03", title: "维修记录便捷上传", desc: "发现问题直接拍照上传，记录故障位置、描述问题。无需手动填写表格，拍完即走，后台自动生成工单。", color: C.mint },
    { num: "04", title: "兼容安卓与苹果", desc: "Flutter跨平台开发，一套代码同时支持Android和iOS设备，确保所有工人都能使用。", color: C.moss },
  ];

  appFeatures.forEach((feat, i) => {
    const y = 1.2 + i * 1.05;

    // Number
    slide.addText(feat.num, {
      x: 3.5, y: y, w: 0.6, h: 0.4,
      fontSize: 20, fontFace: "Arial Black", color: feat.color, bold: true, margin: 0
    });

    // Title
    slide.addText(feat.title, {
      x: 4.15, y: y, w: 5.3, h: 0.35,
      fontSize: 15, fontFace: "Arial", color: C.darkGray, bold: true, margin: 0
    });

    // Description
    slide.addText(feat.desc, {
      x: 4.15, y: y + 0.35, w: 5.3, h: 0.6,
      fontSize: 11, fontFace: "Calibri", color: C.gray, lineSpacingMultiple: 1.2
    });
  });
}

// ──────────────────────────────────────────────────────────────────
// SLIDE 5: Data Sync - Simple Explanation
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.offWhite };

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.9, fill: { color: C.deepBlue }
  });
  slide.addText("数据同步 — 像收邮件一样简单", {
    x: 0.6, y: 0.15, w: 9, h: 0.6,
    fontSize: 26, fontFace: "Arial Black", color: C.white, margin: 0
  });

  // Step 1: Maxicom computer
  const steps = [
    { x: 0.3, title: "Maxicom 电脑", sub: "（灌溉控制电脑）", 
      desc: "灌溉控制系统每天都在\n自动记录所有浇水数据\n这些数据保存在这台电脑里",
      emoji: "🖥️", color: C.teal },
    { x: 3.45, title: "同步小助手", sub: "（自动运行程序）",
      desc: "一个小程序自动运行\n每5分钟自动\"取信\"\n把新数据安全地传输出去\n无需任何手动操作",
      emoji: "📬", color: C.seafoam },
    { x: 6.6, title: "管理平台", sub: "（手机和电脑都能看）",
      desc: "数据自动显示在平台上\n手机APP随时查看\n管理者能看到所有数据\n就像看微信朋友圈一样简单",
      emoji: "🌐", color: C.mint },
  ];

  steps.forEach((step, i) => {
    // Card
    slide.addShape(pres.shapes.RECTANGLE, {
      x: step.x, y: 1.2, w: 2.9, h: 3.6,
      fill: { color: C.white }, shadow: cardShadow()
    });

    // Top bar
    slide.addShape(pres.shapes.RECTANGLE, {
      x: step.x, y: 1.2, w: 2.9, h: 0.08, fill: { color: step.color }
    });

    // Step number circle
    slide.addShape(pres.shapes.OVAL, {
      x: step.x + 1.05, y: 1.45, w: 0.8, h: 0.8,
      fill: { color: step.color }
    });
    slide.addText(step.emoji, {
      x: step.x + 1.05, y: 1.45, w: 0.8, h: 0.8,
      fontSize: 24, align: "center", valign: "middle"
    });

    // Title
    slide.addText(step.title, {
      x: step.x + 0.15, y: 2.35, w: 2.6, h: 0.35,
      fontSize: 16, fontFace: "Arial", color: C.darkGray, bold: true, align: "center"
    });

    // Subtitle
    slide.addText(step.sub, {
      x: step.x + 0.15, y: 2.65, w: 2.6, h: 0.3,
      fontSize: 11, fontFace: "Calibri", color: step.color, align: "center"
    });

    // Description
    slide.addText(step.desc, {
      x: step.x + 0.2, y: 3.05, w: 2.5, h: 1.6,
      fontSize: 12, fontFace: "Calibri", color: C.darkGray, lineSpacingMultiple: 1.4, align: "center"
    });
  });

  // Arrows
  slide.addText("➜", {
    x: 3.05, y: 2.6, w: 0.5, h: 0.5,
    fontSize: 28, color: C.seafoam, align: "center", bold: true
  });
  slide.addText("➜", {
    x: 6.15, y: 2.6, w: 0.5, h: 0.5,
    fontSize: 28, color: C.mint, align: "center", bold: true
  });

  // Bottom note
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.3, y: 5.0, w: 9.4, h: 0.45,
    fill: { color: C.gold, transparency: 70 }
  });
  slide.addText("💡 重要：所有操作都在您的Maxicom电脑上自动完成，完全不会影响灌溉系统的正常运行", {
    x: 0.5, y: 5.0, w: 9.0, h: 0.45,
    fontSize: 13, fontFace: "Calibri", color: C.darkGray, align: "center", valign: "middle"
  });
}

// ──────────────────────────────────────────────────────────────────
// SLIDE 6: Summary & Next Steps
// ──────────────────────────────────────────────────────────────────
{
  const slide = pres.addSlide();
  slide.background = { color: C.navy };

  // Top accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.08, fill: { color: C.mint }
  });

  slide.addText("总结与下一步", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 32, fontFace: "Arial Black", color: C.white
  });

  // Left: What we deliver
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.4, w: 4.3, h: 3.5,
    fill: { color: "FFFFFF", transparency: 8 }
  });

  slide.addText("我们提供", {
    x: 0.7, y: 1.6, w: 3.9, h: 0.4,
    fontSize: 18, fontFace: "Arial", color: C.mint, bold: true
  });

  const deliverables = [
    { text: "Django 数据管理平台 — 网页端管理所有数据", options: { bullet: true, breakLine: true, fontSize: 13, color: C.white, paraSpaceAfter: 10 } },
    { text: "Flutter 手机APP — 地图 + 维修记录 + 实时数据", options: { bullet: true, breakLine: true, fontSize: 13, color: C.white, paraSpaceAfter: 10 } },
    { text: "Maxicom 同步程序 — 全自动，无需操作", options: { bullet: true, breakLine: true, fontSize: 13, color: C.white, paraSpaceAfter: 10 } },
    { text: "完全独立于灌溉系统 — 不影响现有运行", options: { bullet: true, breakLine: true, fontSize: 13, color: C.white, paraSpaceAfter: 10 } },
    { text: "服务器部署与运维支持", options: { bullet: true, fontSize: 13, color: C.white, paraSpaceAfter: 10 } },
  ];
  slide.addText(deliverables, {
    x: 0.7, y: 2.1, w: 3.9, h: 2.5
  });

  // Right: Next steps
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 1.4, w: 4.3, h: 3.5,
    fill: { color: "FFFFFF", transparency: 8 }
  });

  slide.addText("下一步计划", {
    x: 5.4, y: 1.6, w: 3.9, h: 0.4,
    fontSize: 18, fontFace: "Arial", color: C.gold, bold: true
  });

  const nextSteps = [
    { num: "1", text: "确认功能需求与优先级" },
    { num: "2", text: "获取灌溉地图底图 (CAD/航拍)" },
    { num: "3", text: "部署Django服务器" },
    { num: "4", text: "开发并测试移动端APP" },
    { num: "5", text: "安装同步程序，开始数据采集" },
  ];

  nextSteps.forEach((step, i) => {
    const y = 2.2 + i * 0.5;
    slide.addShape(pres.shapes.OVAL, {
      x: 5.5, y: y + 0.05, w: 0.3, h: 0.3,
      fill: { color: C.mint }
    });
    slide.addText(step.num, {
      x: 5.5, y: y + 0.05, w: 0.3, h: 0.3,
      fontSize: 12, fontFace: "Arial", color: C.navy, bold: true, align: "center", valign: "middle"
    });
    slide.addText(step.text, {
      x: 5.95, y: y, w: 3.3, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.white, margin: 0
    });
  });

  // Bottom contact line
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.15, w: 10, h: 0.4, fill: { color: "FFFFFF", transparency: 90 }
  });
  slide.addText("期待与您合作 · 共同打造智能灌溉管理系统", {
    x: 0.5, y: 5.15, w: 9, h: 0.4,
    fontSize: 14, fontFace: "Calibri", color: C.gray, align: "center", valign: "middle"
  });
}

// ──────────────────────────────────────────────────────────────────
// Write file
// ──────────────────────────────────────────────────────────────────
const outputPath = "c:\\Users\\czhou7\\PythonProjects\\irrigation\\docs\\灌溉管理系统解决方案.pptx";
pres.writeFile({ fileName: outputPath }).then(() => {
  console.log("✓ Created: " + outputPath);
}).catch(err => {
  console.error("Error:", err);
});