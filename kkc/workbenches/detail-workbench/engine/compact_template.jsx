/* One compact working document for template preview and editable output. */
var compactKeepRoles = ["header", "hero", "product", "colors", "size_table", "quick_size",
                        "try_on", "measurement_method", "scenes"];

function compactContains(values, value) {
    for (var i = 0; i < values.length; i++) if (values[i] === value) return true;
    return false;
}

function compactClone(value) { return eval("(" + manifestJson(value) + ")"); }

function compactMinimalPaths(paths) {
    var ordered = paths.slice();
    ordered.sort(function (a, b) { return a.length - b.length; });
    var result = [];
    for (var i = 0; i < ordered.length; i++) {
        if (!ordered[i] || !ordered[i].length) continue;
        if (!manifestExcluded(ordered[i], result)) result.push(ordered[i].slice());
    }
    return result;
}

function compactDeleteLayer(layer) {
    var reference = new ActionReference();
    reference.putIdentifier(stringIDToTypeID("layer"), layer.id);
    var descriptor = new ActionDescriptor();
    descriptor.putReference(stringIDToTypeID("null"), reference);
    executeAction(stringIDToTypeID("delete"), descriptor, DialogModes.NO);
}

function compactPruneToPaths(parent, keep, removed) {
    for (var i = parent.layers.length - 1; i >= 0; i--) {
        var layer = parent.layers[i];
        var path = manifestPath(layer);
        var inside = false, ancestor = false;
        for (var j = 0; j < keep.length; j++) {
            if (manifestPrefix(path, keep[j])) inside = true;
            if (manifestPrefix(keep[j], path)) ancestor = true;
        }
        if (inside) continue;
        if (ancestor && layer.typename === "LayerSet") compactPruneToPaths(layer, keep, removed);
        else {
            removed.push(path);
            compactDeleteLayer(layer);
        }
    }
}

function compactShiftRects(value, dy) {
    if (!value || typeof value !== "object") return;
    var names = ["rect", "original_rect", "cover_rect", "label_rect", "image_rect", "mask_rect",
                 "source_rect", "source_cover_rect", "prototype_rect"];
    if (value instanceof Array) {
        for (var i = 0; i < value.length; i++) compactShiftRects(value[i], dy);
        return;
    }
    for (var key in value) {
        if (!value.hasOwnProperty(key)) continue;
        var child = value[key];
        if (compactContains(names, key) && child instanceof Array && child.length === 4 &&
            typeof child[0] === "number" && typeof child[1] === "number") child[1] += dy;
        else compactShiftRects(child, dy);
    }
}

function compactRoleForSlot(key, slot) {
    if (slot.role) return slot.role;
    if (key.indexOf("scene_") === 0) return "scenes";
    if (key === "measurement") return "size_table";
    return key;
}

function compactModulePaths(module) {
    return module.move_paths || (module.path ? [module.path] : []);
}

function compactRoleExtraPaths(profile, module) {
    var paths = [], role = module.role, i;
    if (role === "product") {
        for (var field in profile.fields) {
            var binding = profile.fields[field];
            paths = paths.concat(binding.paths || []);
            if (binding.label_path) paths.push(binding.label_path);
        }
        if (profile.product_attributes) paths.push(profile.product_attributes.path);
    }
    if (role === "colors") paths = paths.concat(profile.colors.data_paths || []);
    if (module.table) {
        paths = paths.concat(module.table.data_paths || []);
        if (module.table.base_path) paths.push(module.table.base_path);
    }
    paths = paths.concat(module.background_paths || []);
    for (i = 0; i < profile.original_images.length; i++) {
        if (profile.original_images[i].role === role) paths.push(profile.original_images[i].path);
    }
    for (var key in profile.view_slots) {
        var slot = profile.view_slots[key];
        if (compactRoleForSlot(key, slot) !== role) continue;
        if (slot.path) paths.push(slot.path);
        if (slot.prototype_path) paths.push(slot.prototype_path);
    }
    if (role === "size_table" && profile.size_note) {
        for (i = 0; i < profile.size_note.lines.length; i++) paths.push(profile.size_note.lines[i].path);
    }
    return paths;
}

function compactNeededPaths(doc, profile) {
    var keep = [];
    for (var i = 0; i < profile.modules.length; i++) keep = keep.concat(compactModulePaths(profile.modules[i]));
    for (i = 0; i < profile.stretch_paths.length; i++) keep.push(profile.stretch_paths[i].path);
    for (var field in profile.fields) {
        var binding = profile.fields[field];
        keep = keep.concat(binding.paths || []);
        if (binding.label_path) keep.push(binding.label_path);
    }
    keep = keep.concat(profile.colors.data_paths || []);
    for (var key in profile.view_slots) {
        var slot = profile.view_slots[key];
        if (slot.path) keep.push(slot.path);
        if (slot.prototype_path) keep.push(slot.prototype_path);
    }
    if (profile.product_attributes) keep.push(profile.product_attributes.path);
    if (profile.size_note) for (i = 0; i < profile.size_note.lines.length; i++) keep.push(profile.size_note.lines[i].path);
    // The existing neutral canvas background is support for every retained page.
    for (i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        if (layer.typename !== "ArtLayer") continue;
        if (layer.isBackgroundLayer || layer.name === "背景") keep.push([layer.name]);
    }
    return compactMinimalPaths(keep);
}

function compactMovePath(doc, path, dy, moved) {
    var key = manifestJson(path);
    for (var i = 0; i < moved.length; i++) {
        if (manifestPrefix(path, moved[i].path)) {
            if (Math.abs(dy - moved[i].dy) > 0.01) throw new Error("精简母版存在交叉移动容器：" + path.join(" / "));
            return;
        }
        if (manifestPrefix(moved[i].path, path)) throw new Error("精简母版先移动了祖先容器内的子项：" + path.join(" / "));
    }
    var matches = manifestResolvePaths(doc, path);
    if (matches.length !== 1) throw new Error("精简母版图层路径不唯一：" + path.join(" / "));
    if (Math.abs(dy) > 0.001) matches[0].translate(UnitValue(0, "px"), UnitValue(dy, "px"));
    moved.push({path: path.slice(), dy: dy});
}

function compactEnsureBackground(doc) {
    for (var i = 0; i < doc.layers.length; i++) {
        var candidate = doc.layers[i];
        if (candidate.typename === "ArtLayer" && (candidate.isBackgroundLayer || candidate.name === "背景")) return;
    }
    // Older classic originals use an enormous pixel composite as their page
    // backing. It is excluded above; replace it with only neutral canvas pixels.
    var layer = doc.artLayers.add();
    layer.name = "背景";
    var bottom = doc.layers[doc.layers.length - 1];
    if (bottom.id !== layer.id) layer.move(bottom, ElementPlacement.PLACEAFTER);
    doc.activeLayer = layer;
    var white = new SolidColor();
    white.rgb.red = white.rgb.green = white.rgb.blue = 255;
    doc.selection.selectAll();
    doc.selection.fill(white, ColorBlendMode.NORMAL, 100, false);
    doc.selection.deselect();
}

function compactClassicHeader(doc, profile) {
    if (profile.family !== "classic" || manifestFindModule(profile, "header")) return;
    var product = manifestFindModule(profile, "product");
    if (!product || !product.path || !product.path.length) return;
    // This known classic family stores the short title and round KK logo as
    // siblings of its information card, rather than in an explicit header group.
    var root = product.path.slice(0, 1);
    var titlePath = root.concat(["这样选更准确"]), logoPath = root.concat(["图层 727"]);
    var titles = manifestResolvePaths(doc, titlePath), logos = manifestResolvePaths(doc, logoPath);
    if (titles.length !== 1 || logos.length !== 1) return;
    var rect = manifestUnion([manifestRect(titles[0]), manifestRect(logos[0])]);
    var top = Math.max(0, rect[1] - 20);
    profile.modules.push({role: "header", path: null, move_paths: [titlePath, logoPath],
        rect: [rect[0], top, rect[2], rect[1] + rect[3] + 20 - top], titles: []});
}

function compactAddHeroExample(doc, profile, spec, reportStage) {
    var hero = manifestFindModule(profile, "hero");
    if (!hero || !hero.generated || !profile.view_slots.hero) return;
    var name = "母版示例 · 主视觉";
    if (manifestResolvePaths(doc, [name]).length) return;
    var example = spec.heroExample ? new File(spec.heroExample) : null;
    var temporary = null, sourceDoc = null;
    var original = profile.original_preview ? new File(profile.original_preview) : null;
    if ((!original || !original.exists) && spec.originalPreview) original = new File(spec.originalPreview);
    try {
        // This validated 790×40000 legacy family has its actual product hero at
        // the known original position. Crop only its cached JPEG, never the PSB.
        var sourceHeight = profile.source_canvas ? profile.source_canvas.height : spec.sourceCanvas ? spec.sourceCanvas[1] : 0;
        if ((!example || !example.exists) && profile.family === "workbench" &&
            sourceHeight === 40000 && original && original.exists) {
            if (reportStage) reportStage("精简母版 · 提取本母版主视觉示例");
            sourceDoc = app.open(original);
            if (sourceDoc.width.as("px") === 790 && sourceDoc.height.as("px") === 40000) {
                sourceDoc.crop([UnitValue(10, "px"), UnitValue(3130, "px"), UnitValue(780, "px"), UnitValue(4650, "px")]);
                temporary = new File(spec.assetsFolder + "/.compact-hero-example.png");
                sourceDoc.saveAs(temporary, new PNGSaveOptions(), true, Extension.LOWERCASE);
                example = temporary;
            }
            sourceDoc.close(SaveOptions.DONOTSAVECHANGES);
            sourceDoc = null;
            app.activeDocument = doc;
        }
        var sourceLayer = null;
        if (!example || !example.exists) {
            if (profile.colors.slots.length && profile.colors.slots[0].image_path) {
                var matches = manifestResolvePaths(doc, profile.colors.slots[0].image_path);
                if (matches.length === 1) sourceLayer = matches[0];
            }
            if (!sourceLayer) throw new Error("此母版主视觉没有原生示例，请提供本母版的主视觉参考图后重试。");
        }
        if (reportStage) reportStage("精简母版 · 嵌入主视觉示例");
        app.activeDocument = doc;
        var group = doc.layerSets.add();
        group.name = name;
        var r = hero.rect, frame = profile.view_slots.hero.rect;
        rectangle(doc, group, "主视觉底色", r[0], r[1], r[2], r[3], hero.fill || [235, 245, 242], hero.radius || 0);
        var clip = rectangle(doc, group, "示例图片框", frame[0], frame[1], frame[2], frame[3], [255, 255, 255], 0);
        if (example && example.exists) {
            workbenchPicture(doc, group, {staged: example.fsName, is_product: true}, "本母版主视觉示例", frame, clip);
        } else {
            var image = sourceLayer.duplicate(group, ElementPlacement.INSIDE);
            if (image.grouped) image.grouped = false;
            var b = box(image), factor = Math.min(frame[2] / (b[2] - b[0]), frame[3] / (b[3] - b[1]));
            image.resize(100 * factor, 100 * factor, AnchorPosition.MIDDLECENTER);
            b = box(image);
            image.translate(UnitValue(frame[0] + frame[2] / 2 - (b[0] + b[2]) / 2, "px"),
                            UnitValue(frame[1] + frame[3] / 2 - (b[1] + b[3]) / 2, "px"));
            image.move(clip, ElementPlacement.PLACEBEFORE);
            image.grouped = true;
        }
        var fonts = loadDetailMixedFonts();
        workbenchText(group, "示例标题", "主视觉示例", r[0] + 40, r[1] + 135, r[2] - 80, 52, fonts);
        workbenchText(group, "示例说明", "母版版式参考", r[0] + 44, r[1] + 225, r[2] - 88, 29, fonts);
        workbenchText(group, "示例底部说明", "主视觉图位", r[0] + 44, frame[1] + frame[3] + 160, r[2] - 88, 32, fonts);
        profile.original_images.push({path: [name], role: "hero", kind: "template_example"});
        profile.content_policy.keep_paths.push([name]);
        profile.compact_summary.hero_example = {embedded: true, clear_on_export: true, from_same_template: true};
    } finally {
        if (sourceDoc) { try { sourceDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        if (temporary && temporary.exists) temporary.remove();
        app.activeDocument = doc;
    }
}

function compactAddSceneExamples(doc, profile, spec, reportStage) {
    var i;
    for (i = 0; i < profile.original_images.length; i++) if (profile.original_images[i].role === "scenes") return;
    var examples = spec.sceneExamples || [];
    var sourceHeight = profile.source_canvas ? profile.source_canvas.height : spec.sourceCanvas ? spec.sourceCanvas[1] : 0;
    var original = profile.original_preview ? new File(profile.original_preview) : null;
    if ((!original || !original.exists) && spec.originalPreview) original = new File(spec.originalPreview);
    var useOriginal = !examples.length && profile.family === "workbench" && sourceHeight === 40000 && original && original.exists;
    if (!examples.length && !useOriginal) return;
    var sourceDoc = null, cropDoc = null, temporary = null, count = 0;
    var rawFrames = [[8, 30875, 768, 1081], [91, 32098, 602, 789], [8, 33062, 768, 1010], [8, 34127, 768, 1010]];
    try {
        if (useOriginal) {
            if (reportStage) reportStage("精简母版 · 读取本母版模特示例");
            sourceDoc = app.open(original);
            if (sourceDoc.width.as("px") !== 790 || sourceDoc.height.as("px") !== 40000) return;
        }
        for (i = 0; i < 4; i++) {
            var key = "scene_" + (i + 1), slot = profile.view_slots[key];
            if (!slot || !slot.path || slot.generated) continue;
            var imageFile = examples[i] ? new File(examples[i]) : null;
            if (useOriginal) {
                app.activeDocument = sourceDoc;
                cropDoc = sourceDoc.duplicate("本母版模特图示例", true);
                var raw = rawFrames[i];
                cropDoc.crop([UnitValue(raw[0], "px"), UnitValue(raw[1], "px"),
                              UnitValue(raw[0] + raw[2], "px"), UnitValue(raw[1] + raw[3], "px")]);
                temporary = new File(spec.assetsFolder + "/.compact-scene-example-" + (i + 1) + ".png");
                cropDoc.saveAs(temporary, new PNGSaveOptions(), true, Extension.LOWERCASE);
                cropDoc.close(SaveOptions.DONOTSAVECHANGES);
                cropDoc = null;
                imageFile = temporary;
            }
            if (!imageFile || !imageFile.exists) continue;
            if (reportStage) reportStage("精简母版 · 嵌入模特示例 " + (i + 1));
            app.activeDocument = doc;
            var clip = findLayer(doc, slot.path);
            var picture = workbenchPicture(doc, clip.parent, {staged: imageFile.fsName, is_product: false},
                "母版示例 · 模特图" + (i + 1), slot.rect, clip);
            var imagePath = manifestPath(picture);
            profile.original_images.push({path: imagePath, role: "scenes", kind: "template_example"});
            profile.content_policy.keep_paths.push(imagePath);
            count++;
            if (temporary && temporary.exists) temporary.remove();
            temporary = null;
        }
        if (count) profile.compact_summary.scene_examples = {embedded: count, clear_on_export: true, from_same_template: true};
    } finally {
        if (cropDoc) { try { cropDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (cropError) {} }
        if (sourceDoc) { try { sourceDoc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        if (temporary && temporary.exists) temporary.remove();
        app.activeDocument = doc;
    }
}

function compactProfileDocument(doc, source, reportStage) {
    var profile = compactClone(source);
    if (profile.compact_version === 1) return profile;
    compactClassicHeader(doc, profile);
    var originalCanvas = compactClone(profile.canvas);
    var removedRoles = [], modules = [], i, j;
    for (i = 0; i < profile.modules.length; i++) {
        var module = profile.modules[i];
        if (compactContains(compactKeepRoles, module.role)) {
            delete module.skin_backgrounds;
            delete module.skin_foreground;
            if (module.table) { delete module.table.mask; delete module.table.mask_rect; }
            modules.push(module);
        } else removedRoles.push(module.role);
    }
    if (!modules.length || !manifestFindModule({modules: modules}, "product") || !manifestFindModule({modules: modules}, "colors")) {
        throw new Error("精简母版缺少商品资料或颜色模块");
    }
    profile.modules = modules;
    for (var key in profile.view_slots) {
        if (!compactContains(compactKeepRoles, compactRoleForSlot(key, profile.view_slots[key]))) delete profile.view_slots[key];
    }
    var images = [];
    for (i = 0; i < profile.original_images.length; i++) {
        if (compactContains(compactKeepRoles, profile.original_images[i].role)) images.push(profile.original_images[i]);
    }
    profile.original_images = images;
    var stretches = [];
    for (i = 0; i < profile.stretch_paths.length; i++) {
        if (compactContains(compactKeepRoles, profile.stretch_paths[i].role)) stretches.push(profile.stretch_paths[i]);
    }
    profile.stretch_paths = stretches;
    var removed = [];
    if (reportStage) reportStage("精简母版 · 清除原稿无关内容");
    for (i = 0; i < profile.omitted_paths.length; i++) {
        var omission = profile.omitted_paths[i];
        if (profile.product_attributes && manifestJson(omission) === manifestJson(profile.product_attributes.path)) continue;
        var omitted = manifestResolvePaths(doc, omission);
        for (j = omitted.length - 1; j >= 0; j--) { removed.push(omission.slice()); compactDeleteLayer(omitted[j]); }
    }
    var keep = compactNeededPaths(doc, profile);
    compactPruneToPaths(doc, keep, removed);
    profile.modules.sort(function (a, b) { return a.rect[1] - b.rect[1]; });
    var shifts = {}, gaps = [], end = 0, sourceEnd = 0, previous = null;
    for (i = 0; i < profile.modules.length; i++) {
        module = profile.modules[i];
        var sourceRect = module.rect.slice();
        var gap;
        if (!previous) gap = module.role === "header" ? 0 : 20;
        else if ((previous === "product" && module.role === "colors") ||
                 (previous === "size_table" && module.role === "measurement_method")) gap = 0;
        else gap = Math.max(0, Math.min(60, sourceRect[1] - sourceEnd));
        var top = end + gap;
        shifts[module.role] = top - sourceRect[1];
        gaps.push({role: module.role, before: sourceRect[1] - sourceEnd, after: gap});
        sourceEnd = sourceRect[1] + sourceRect[3];
        end = top + sourceRect[3];
        previous = module.role;
    }
    // Capture shared backings before moving their individual content children.
    var shared = [];
    for (i = 0; i < profile.stretch_paths.length; i++) {
        var stretch = profile.stretch_paths[i], backing = findLayer(doc, stretch.path), bounds = manifestRect(backing);
        var owner = stretch.role;
        for (j = 0; j < profile.modules.length; j++) {
            module = profile.modules[j];
            if (bounds[1] >= module.rect[1] - 2 && bounds[1] < module.rect[1] + module.rect[3] - 2) { owner = module.role; break; }
        }
        shared.push({path: stretch.path, owner: owner, tail: stretch.role, rect: bounds});
    }
    var moved = [];
    for (i = 0; i < profile.modules.length; i++) {
        module = profile.modules[i];
        if (reportStage) reportStage("精简母版 · 排列 " + module.role);
        // Earlier column templates store color photographs as siblings of the
        // color-label group. Dynamic bindings therefore participate in the same
        // physical translation, even when outside module.move_paths.
        var paths = compactMinimalPaths(compactModulePaths(module).concat(compactRoleExtraPaths(profile, module)));
        for (j = 0; j < paths.length; j++) compactMovePath(doc, paths[j], shifts[module.role], moved);
    }
    for (i = 0; i < shared.length; i++) {
        var item = shared[i];
        compactMovePath(doc, item.path, shifts[item.owner] || 0, moved);
        var delta = (shifts[item.tail] || 0) - (shifts[item.owner] || 0);
        if (Math.abs(delta) > 0.001) {
            var shape = findLayer(doc, item.path), before = box(shape), oldHeight = before[3] - before[1];
            if (oldHeight + delta <= 0) throw new Error("精简母版共用底板高度无效");
            shape.resize(100, 100 * (oldHeight + delta) / oldHeight, AnchorPosition.TOPCENTER);
            var after = box(shape);
            shape.translate(UnitValue(before[0] - after[0], "px"), UnitValue(before[1] - after[1], "px"));
        }
    }
    for (i = 0; i < profile.modules.length; i++) compactShiftRects(profile.modules[i], shifts[profile.modules[i].role]);
    compactShiftRects(profile.fields, shifts.product || 0);
    compactShiftRects(profile.colors, shifts.colors || 0);
    compactShiftRects(profile.product_attributes, shifts.product || 0);
    compactShiftRects(profile.size_note, shifts.size_table || 0);
    for (i = 0; i < profile.original_images.length; i++) compactShiftRects(profile.original_images[i], shifts[profile.original_images[i].role] || 0);
    for (key in profile.view_slots) compactShiftRects(profile.view_slots[key], shifts[compactRoleForSlot(key, profile.view_slots[key])] || 0);
    delete profile.decorations;
    delete profile.skin_version;
    profile.canvas = {width: 790, height: Math.ceil(end + 20)};
    profile.compact_version = 1;
    profile.content_policy = {version: 1, keep_roles: compactKeepRoles.slice(), excluded_roles: ["brand", "footer"], keep_paths: keep};
    var retainedRoles = [];
    for (i = 0; i < profile.modules.length; i++) retainedRoles.push(profile.modules[i].role);
    profile.compact_summary = {source_canvas: originalCanvas, canvas: compactClone(profile.canvas),
        kept_roles: retainedRoles, removed_roles: removedRoles, removed_paths: compactMinimalPaths(removed), gaps: gaps,
        original_source_modified: false};
    doc.resizeCanvas(UnitValue(profile.canvas.width, "px"), UnitValue(profile.canvas.height, "px"), AnchorPosition.TOPCENTER);
    compactEnsureBackground(doc);
    if (!manifestExcluded(["背景"], keep)) keep.push(["背景"]);
    return profile;
}

function compactWorkbenchTemplate(spec) {
    var units = app.preferences.rulerUnits, dialogs = app.displayDialogs;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc;
    function stage(name) { templateImportStage(spec, name); }
    try {
        app.preferences.rulerUnits = Units.PIXELS;
        app.displayDialogs = DialogModes.NO;
        stage("精简母版 · 打开独立工作副本");
        doc = app.open(new File(spec.source));
        doc.activeChannels = doc.componentChannels;
        doc.selection.deselect();
        var profile = compactProfileDocument(doc, spec.profile, stage);
        compactAddHeroExample(doc, profile, spec, stage);
        compactAddSceneExamples(doc, profile, spec, stage);
        profile = extractManifestAssetsFromProfile(doc, spec, profile, stage);
        stage("精简母版 · 保存必要页面工作母版");
        app.activeDocument = doc;
        saveDetailPsb(new File(spec.output));
        if (spec.headerPreview) writeTemplatePreview(doc, spec.headerPreview, 0, Math.min(doc.height.as("px"), 500));
        if (spec.footerPreview) writeTemplatePreview(doc, spec.footerPreview, Math.max(0, doc.height.as("px") - 2), doc.height.as("px"));
        if (spec.reportOutput) manifestWrite(spec.reportOutput, profile.compact_summary);
        stage("精简母版 · 完成");
        return profile;
    } finally {
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
}
