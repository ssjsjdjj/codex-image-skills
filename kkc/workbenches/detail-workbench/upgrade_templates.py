"""Extract template manifests or repair the complete saved-source references."""

import argparse
import json

from templates import list_templates, repair_original_preview, repair_template_masks, upgrade_template


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-only", action="store_true", help="只修复原稿完整参考，不重提取套版布局")
    parser.add_argument("--masks-only", action="store_true", help="只修复原生图框轮廓蒙版")
    parser.add_argument("--template-id", help="仅处理指定母版ID")
    parser.add_argument("--source", help="替换所选母版的原稿路径（需 --reference-only 和 --template-id）")
    arguments = parser.parse_args()
    if arguments.reference_only and arguments.masks_only:
        parser.error("--reference-only 与 --masks-only 不可同时使用")
    if arguments.source and not (arguments.reference_only and arguments.template_id):
        parser.error("--source 需要同时指定 --reference-only 和 --template-id")
    templates = [item for item in list_templates() if not arguments.template_id or item.id == arguments.template_id]
    if not templates:
        parser.error("未找到指定母版")
    failed = False
    for template in templates:
        if arguments.masks_only:
            print(f"正在修复 {template.label} 的原生图框蒙版", flush=True)
            report = repair_template_masks(template)
            print(json.dumps({"id": template.id, "label": template.label, "masks": report}, ensure_ascii=False), flush=True)
            continue
        if arguments.reference_only:
            print(f"正在修复 {template.label} 的原稿完整参考", flush=True)
            info = repair_original_preview(template, source=arguments.source)
            print(json.dumps({"id": template.id, "label": template.label, **info}, ensure_ascii=False), flush=True)
            failed = failed or info["status"] != "ready"
            continue
        print(f"正在提取 {template.label} · {template.dimensions[0]} × {template.dimensions[1]}", flush=True)
        upgrade_template(template)
        profile = template.profile()
        print(f"已完成 {template.label} · {len(profile['modules'])} 个模块 · 原色图 {profile['colors']['original_count']} 张", flush=True)
    raise SystemExit(1 if failed else 0)
