"""Isolated acceptance: per-style PSDs, both folder modes, real CPU inference and safety."""
import argparse
import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from psd_tools import PSDImage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--work", required=True)
    args = parser.parse_args()
    skill, work = Path(args.skill).resolve(), Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    checks = []
    report = {"passed": False, "checks": checks, "python": sys.executable, "versions": {},
              "work": str(work), "model": "u2net", "model_inference": False, "scenarios": []}

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        print(("PASS " if condition else "FAIL ") + name, flush=True)
        if not condition:
            raise AssertionError(name + (": " + str(detail) if detail else ""))

    def run(*arguments, success=True):
        result = subprocess.run([sys.executable, str(skill / "scripts/launch.py"), *map(str, arguments)],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=600,
                                env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1"))
        with (work / "commands.log").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps([str(a) for a in arguments], ensure_ascii=False) + "\n" + result.stdout + result.stderr + "\n")
        if success and result.returncode:
            raise RuntimeError(result.stderr[-5000:] or result.stdout[-5000:])
        return result

    def save_spec(name, value):
        path = work / (name + ".json")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def snapshot(folder):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob("*") if p.is_file()}

    def same_rgba(actual, expected):
        a, b = np.asarray(actual.convert("RGBA")).astype(int), np.asarray(expected.convert("RGBA")).astype(int)
        if a.shape != b.shape or np.max(np.abs(a[:, :, 3] - b[:, :, 3])) > 1:
            return False
        visible = b[:, :, 3] > 0
        return bool(np.max(np.abs(a[:, :, :3][visible] - b[:, :, :3][visible]), initial=0) <= 2)

    def inspect(result, tag):
        root = Path(result["out_dir"])
        actual = {str(p) for p in root.rglob("*") if p.is_file()}
        check(tag + " exact formal file list", actual == set(result["outputs"]) and len(actual) == result["total_files"])
        check(tag + " 2N+2K counts", result["image_count"] == 2 * result["input_count"] and
              result["psd_count"] == 2 * result["style_count"] and result["total_files"] == result["image_count"] + result["psd_count"])
        check(tag + " manifest maps every file", {f["path"] for f in result["files"]} == actual)
        for group in result["styles"]:
            style = group["style"]
            names = [j["layer_name"] for j in group["images"]]
            pngs = []
            for job in group["images"]:
                label = f"{tag}/{style}/{job['layer_name']}"
                with Image.open(job["white"]) as white, Image.open(job["transparent"]) as png:
                    white.load(); png.load(); png = png.convert("RGBA")
                    check(label + " images within 500KB", all(Path(job[k]).stat().st_size <= 500_000 for k in ("white", "transparent")))
                    check(label + " image dimensions and modes", white.size == png.size == (800, 800) and white.mode == "RGB" and png.mode == "RGBA")
                    check(label + " JPG white corners", all(min(white.getpixel(p)) >= 250 for p in ((0,0),(799,0),(0,799),(799,799))))
                    alpha = png.getchannel("A")
                    box = alpha.getbbox()
                    check(label + " valid transparent alpha", box is not None and alpha.getextrema()[0] == 0 and alpha.getextrema()[1] > 200)
                    occupancy = max(box[2]-box[0], box[3]-box[1]) / 800
                    check(label + " fill and centering", abs(occupancy - job["fill"]) <= .02 and
                          abs((box[0]+box[2])/2-400) <= 2 and abs((box[1]+box[3])/2-400) <= 2, box)
                    expected_parent = Path(result["out_dir"]) / style
                    if result["separate_image_folders"]:
                        expected_white = expected_parent / "白底图" / (job["layer_name"] + ".jpg")
                        expected_trans = expected_parent / "透明图" / (job["layer_name"] + ".png")
                    else:
                        expected_white = expected_parent / (job["layer_name"] + "-白底.jpg")
                        expected_trans = expected_parent / (job["layer_name"] + "-透明.png")
                    check(label + " selected folder layout", Path(job["white"]) == expected_white and Path(job["transparent"]) == expected_trans)
                    pngs.append(png.copy())
            for kind in ("white", "transparent"):
                path = Path(group["psd"][kind])
                psd = PSDImage.open(path)
                label = f"{tag}/{style}/{kind}PSD"
                background = kind == "white"
                products = list(psd)[1:] if background else list(psd)
                check(label + " exact style filename", path.name == style + ("-白底.psd" if background else "-透明.psd"))
                check(label + " canvas and layer names", psd.size == (800,800) and [l.name for l in psd] == (["背景"] if background else []) + names)
                check(label + " default visibility", [l.visible for l in products] == [True] + [False] * (len(products)-1) and (not background or psd[0].visible))
                expected_first = pngs[0]
                if background:
                    base = Image.new("RGBA", (800,800), "white"); base.alpha_composite(expected_first); expected_first = base
                check(label + " reopen cached and fresh composites", same_rgba(psd.composite(), expected_first) and same_rgba(psd.composite(force=True), expected_first))
                if not background:
                    check(label + " merged transparency", psd.channels == 4 and psd._record.layer_and_mask_information.layer_info.layer_count == -len(products))
                for index, (product, png) in enumerate(zip(products, pngs)):
                    for i, layer in enumerate(products):
                        layer.visible = i == index
                    expected = png
                    if background:
                        expected = Image.new("RGBA", (800,800), "white"); expected.alpha_composite(png)
                    check(label + "/" + product.name + " independent color composite", same_rgba(psd.composite(force=True), expected))
                    box = png.getchannel("A").getbbox()
                    check(label + "/" + product.name + " layer position", max(abs(a-b) for a,b in zip(product.bbox, box)) <= 2, list(product.bbox))
                check(label + " editable product pixels", all(p.topil().mode == "RGBA" and p.width > 0 and p.height > 0 for p in products))

    try:
        for package in ("Pillow", "numpy", "psd-tools", "rembg", "onnxruntime", "numba", "PyYAML"):
            report["versions"][package] = importlib.metadata.version(package)
        config = json.loads((skill / "runtime.json").read_text(encoding="utf-8-sig"))
        check("dedicated interpreter retained", Path(config["python"]).resolve() == Path(sys.executable).resolve())
        sources = work / "src"; sources.mkdir()
        colors = [(35,123,173), (153,72,163), (225,154,40), (38,158,102), (201,77,73)]
        inputs = []
        for index, color in enumerate(colors):
            image = Image.new("RGBA", (520,760), (0,0,0,0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((205-index*12,55+index*8,365,570), 35, fill=(*color,255))
            draw.rounded_rectangle((70,500,370,660), 45, fill=(*color,255))
            draw.rectangle((95,635,365,675), fill=(30,57,77,255))
            draw.rectangle((220,85,350,110+index*10), fill=(245,202,55,255))
            path = sources / f"test-{index}.png"; image.save(path); inputs.append(path)
        original_hashes = snapshot(sources)
        result = run("-h")
        check("CLI exposes plan preview batch make queue idle", all(c in result.stdout for c in ("plan","preview","batch","make","queue","idle")))
        labels = ["蓝色", "紫色", "黄色", "绿色", "红色"]
        for separate in (True, False):
            for counts in ((3,), (2,3)):
                tag = ("separate" if separate else "together") + "-" + "-".join(map(str,counts))
                jobs = []
                cursor = 0
                for style_index, count in enumerate(counts):
                    for color_index in range(count):
                        jobs.append({"style": "款式" + chr(65+style_index), "color": labels[cursor], "input": str(inputs[cursor])})
                        cursor += 1
                spec = {"schema_version":2, "defaults":{"out_dir":str(work / tag),"separate_image_folders":separate}, "jobs":jobs}
                spec_path = save_spec(tag, spec)
                planning = json.loads(run("plan", "--spec", spec_path).stdout)
                expected = 2 * sum(counts) + 2 * len(counts)
                check(tag + " planning correct, no formal files", planning["total_files"] == expected and not Path(planning["out_dir"]).exists())
                preview = json.loads(run("preview", "--spec", spec_path, "--out", work / (tag + "-preview.png"), "--limit", 0).stdout)
                check(tag + " preview covers all mapping and no final files", preview["shown"] == sum(counts) and preview["total_files"] == expected and preview["formal_files_written"] == 0 and not Path(planning["out_dir"]).exists())
                manifest = work / (tag + "-manifest.json")
                result = json.loads(run("batch", "--spec", spec_path, "--manifest", manifest).stdout)
                check(tag + " returned JSON and saved manifest agree", result == json.loads(manifest.read_text(encoding="utf-8")) and result["passed"] is True)
                inspect(result, tag)
                before = snapshot(Path(result["out_dir"]))
                repeat = run("batch", "--spec", spec_path, success=False)
                check(tag + " existing files rejected unchanged", repeat.returncode != 0 and "已存在" in repeat.stderr and before == snapshot(Path(result["out_dir"])))
                report["scenarios"].append({"name":tag,"inputs":sum(counts),"styles":len(counts),"formal_files":expected,"output":result["out_dir"],"preview":preview["preview"]})
        angle_spec = {"defaults":{"out_dir":str(work / "angles"), "separate_image_folders":True, "fill":.7}, "jobs":[
            {"style":"多角度款", "color":"蓝色", "angle":"正面", "input":str(inputs[0])},
            {"style":"多角度款", "color":"蓝色", "angle":"侧面", "input":str(inputs[1])}]}
        angle_result = json.loads(run("batch", "--spec", save_spec("angles", angle_spec)).stdout)
        inspect(angle_result, "same-color-angles-70percent")
        check("same color two angles retained", angle_result["input_count"] == 2 and angle_result["psd_count"] == 2 and [j["layer_name"] for j in angle_result["jobs"]] == ["蓝色-正面", "蓝色-侧面"])
        base = {"defaults":{"out_dir":str(work / "rejected"),"separate_image_folders":False},"jobs":[
            {"style":"测试款", "color":"一", "input":str(inputs[0])},
            {"style":"测试款", "color":"二", "input":str(inputs[1])}]}
        invalid = []
        duplicate = copy.deepcopy(base); duplicate["jobs"][1]["color"] = "一"; invalid.append(("single-character duplicate", duplicate, "同名冲突"))
        duplicate = copy.deepcopy(base); duplicate["jobs"][0]["color"] = "Blue"; duplicate["jobs"][1]["color"] = "blue"; invalid.append(("case-insensitive duplicate", duplicate, "同名冲突"))
        duplicate = copy.deepcopy(base); duplicate["jobs"][0]["style"] = "StyleA"; duplicate["jobs"][1]["style"] = "stylea"; invalid.append(("case-insensitive style ambiguity", duplicate, "大小写冲突"))
        for name in ("CON", "blue?", "../越界", "颜色.", "颜色 ", "COM1.txt"):
            bad = copy.deepcopy(base); bad["jobs"][0]["color"] = name; invalid.append(("invalid Windows name " + name, bad, "Windows"))
        bad = copy.deepcopy(base); bad["defaults"]["fill"] = 1.2; invalid.append(("invalid fill", bad, "超出范围"))
        bad = copy.deepcopy(base); del bad["defaults"]["separate_image_folders"]; del bad["jobs"][0]["style"]; del bad["jobs"][1]["color"]; invalid.append(("missing mapping collected once", bad, "第2项缺少"))
        bad = copy.deepcopy(base); bad["defaults"]["separate_image_folders"] = "false"; invalid.append(("boolean option enforced", bad, "true或false"))
        for index, (label, bad, expected_error) in enumerate(invalid):
            failed = run("batch", "--spec", save_spec(f"invalid-{index}", bad), success=False)
            check(label + " blocked before write", failed.returncode != 0 and expected_error in failed.stderr and not (work / "rejected").exists())
        collision = work / "partial-existing" / "测试款"; collision.mkdir(parents=True)
        sentinel = collision / "一-白底.jpg"; sentinel.write_bytes(b"existing user file")
        bad = copy.deepcopy(base); bad["defaults"]["out_dir"] = str(collision.parent)
        failed = run("batch", "--spec", save_spec("partial-existing", bad), success=False)
        check("single existing target blocks whole batch", failed.returncode != 0 and sentinel.read_bytes() == b"existing user file" and len(snapshot(collision.parent)) == 1)
        spec_path = save_spec("preview-safety", base)
        failed = run("preview", "--spec", spec_path, "--out", work / "rejected" / "preview.png", success=False)
        check("preview cannot pollute formal directory", failed.returncode != 0 and not (work / "rejected").exists())
        failed = run("preview", "--spec", spec_path, "--out", inputs[0], success=False)
        check("preview cannot overwrite input", failed.returncode != 0 and snapshot(sources) == original_hashes)
        module_spec = importlib.util.spec_from_file_location("failure_test_engine", skill / "scripts/bg_assets.py")
        engine = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(engine)
        injected = copy.deepcopy(base); injected["defaults"]["out_dir"] = str(work / "psd-failure")
        def broken_writer(*args, **kwargs):
            raise RuntimeError("injected PSD failure")
        engine.write_psd = broken_writer
        failure = ""
        try:
            engine.batch(engine.build_plan(injected))
        except RuntimeError as error:
            failure = str(error)
        check("PSD failure is incomplete and writes no formal files", "injected PSD failure" in failure and not (work / "psd-failure").exists())
        report["psd_failure_detail"] = failure
        queue = work / "queue.jsonl"
        run("queue", "--file", queue, "--task", json.dumps({"action":"selftest only"}))
        check("PS queue still works without Photoshop", json.loads(queue.read_text(encoding="utf-8").splitlines()[0])["status"] == "pending")
        check("idle query works", float(run("idle").stdout.strip()) >= 0)
        with Image.open(inputs[0]) as transparent:
            opaque = Image.new("RGB", transparent.size, (226,228,216)); opaque.paste(transparent, mask=transparent.getchannel("A"))
        opaque_path = sources / "cpu-model.jpg"; opaque.save(opaque_path, quality=96)
        original_hashes[str(opaque_path)] = hashlib.sha256(opaque_path.read_bytes()).hexdigest()
        print("RUN forced u2net CPU inference (local model)", flush=True)
        model_result = json.loads(run("make", "--input", opaque_path, "--out-dir", work / "model-output", "--style", "CPU模型测试", "--color", "蓝色", "--separate-image-folders", "--cutout", "rembg").stdout)
        inspect(model_result, "forced-u2net-CPU")
        report["model_inference"] = True
        model = Path(config["model_dir"]) / "u2net.onnx"
        md5 = hashlib.md5(model.read_bytes()).hexdigest()
        check("u2net upstream checksum unchanged", md5 == "60024c5c889badc19c04ad937298a77b", md5)
        report["model_path"], report["model_md5"] = str(model), md5
        check("all source hashes unchanged", snapshot(sources) == original_hashes)
        import yaml
        metadata = yaml.safe_load((skill / "SKILL.md").read_text(encoding="utf-8").split("---",2)[1])
        check("skill YAML metadata valid", metadata["name"] == "chutu-baidi-touming" and bool(metadata["description"]))
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        report["traceback"] = traceback.format_exc()
        print(report["traceback"], file=sys.stderr)
    report["passed_checks"] = sum(c["passed"] for c in checks)
    report["total_checks"] = len(checks)
    path = work / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed":report["passed"], "passed_checks":report["passed_checks"], "total_checks":report["total_checks"], "report":str(path)}, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
