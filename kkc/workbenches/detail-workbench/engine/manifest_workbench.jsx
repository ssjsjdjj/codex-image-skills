/* Render only dynamic data; original title and decoration layers stay native. */
function manifestShiftRect(rect, dy) {
    return [rect[0], rect[1] + dy, rect[2], rect[3]];
}

function manifestRoleForSlot(key) {
    return key.indexOf("scene_") === 0 ? "scenes" : key;
}

function manifestNativeText(doc, group, name, value, rect, style, fonts) {
    style = style || {};
    var planned = workbenchActiveJob && workbenchActiveJob.text_layout ? workbenchActiveJob.text_layout[name] : null;
    var px, lines, leading;
    if (planned) {
        if (!planned.rect || planned.rect.length !== 4 || !planned.lines || !planned.lines.length ||
            !isFinite(planned.px) || planned.px < 16 || !isFinite(planned.leading) || planned.leading <= 0) {
            throw new Error("统一文字布局无效：" + name);
        }
        if (String(planned.value) !== String(value) ||
            planned.lines.join("").replace(/[\r\n]/g, "") !== String(value).replace(/[\r\n]/g, "")) {
            throw new Error("统一文字布局与商品资料不符：" + name);
        }
        rect = planned.rect;
        px = planned.px;
        lines = planned.lines;
        leading = planned.leading;
    } else {
        px = Math.max(12, Math.min(80, style.size_px || 24));
        lines = wrapClassicMaterial(String(value), rect[2] - 4, px);
        while (px > 12 && lines.length * px * 1.18 > rect[3]) {
            px--;
            lines = wrapClassicMaterial(String(value), rect[2] - 4, px);
        }
        // A slash is product data, not a closing punctuation mark.
        while (px > 16 && lines.length > 1 && /^[\s）)】\]》〉」』”’]+[，。！？、；：,.!?;:]*\s*$/.test(lines[lines.length - 1])) {
            px--;
            lines = wrapClassicMaterial(String(value), rect[2] - 4, px);
        }
        if (lines.length * px * 1.1 > rect[3] + 4) throw new Error("文字超出母版字段，请缩短内容：" + name);
        leading = px * 1.15;
    }
    var align = style.align === "right" ? Justification.RIGHT : style.align === "center" ? Justification.CENTER : Justification.LEFT;
    var x = style.align === "right" ? rect[0] + rect[2] : style.align === "center" ? rect[0] + rect[2] / 2 : rect[0];
    var face = installedFont([style.font || fonts.cn.postScriptName, fonts.cn.postScriptName]);
    // The shared plan already fits the actual fonts; disable tableText's independent shrink.
    var layer = tableText(group, name, lines.join("\r"), x, rect[1] + px, planned ? 300000 : rect[2], px,
                          style.color || workbenchInk, face, align, fonts);
    layer.textItem.useAutoLeading = false;
    layer.textItem.leading = UnitValue(leading * 72 / doc.resolution, "pt");
    return layer;
}

function manifestMoveLayer(layer, dy) {
    if (Math.abs(dy) > 0.001) layer.translate(UnitValue(0, "px"), UnitValue(dy, "px"));
}

function manifestResizeBackground(layer, heightDelta) {
    if (Math.abs(heightDelta) < 0.001) return;
    var before = box(layer);
    var height = before[3] - before[1];
    if (height + heightDelta <= 0) throw new Error("模块底色高度无效：" + layer.name);
    layer.resize(100, 100 * (height + heightDelta) / height, AnchorPosition.TOPCENTER);
    var after = box(layer);
    layer.translate(UnitValue(before[0] - after[0], "px"), UnitValue(before[1] - after[1], "px"));
}

function applyManifestGeometry(doc, job) {
    var profile = job.profile;
    var geometry = job.geometry;
    var moved = [];
    for (var i = 0; i < profile.modules.length; i++) {
        var source = profile.modules[i];
        var target = geometry.modules[source.role];
        if (!target || source.generated) continue;
        var paths = source.move_paths || (source.path ? [source.path] : []);
        for (var j = 0; j < paths.length; j++) {
            var serialized = manifestJson(paths[j]);
            var handled = false;
            for (var k = 0; k < moved.length; k++) if (moved[k] === serialized) handled = true;
            if (handled) continue;
            var matches = manifestResolvePaths(doc, paths[j]);
            if (!target.visible) {
                for (k = matches.length - 1; k >= 0; k--) matches[k].visible = false;
            } else {
                for (k = 0; k < matches.length; k++) manifestMoveLayer(matches[k], target.delta_y || 0);
            }
            moved.push(serialized);
        }
        if (!target.visible) continue;
        var backgrounds = source.background_paths || [];
        for (j = 0; j < backgrounds.length; j++) {
            manifestResizeBackground(findLayer(doc, backgrounds[j]), target.height_delta || 0);
        }
        for (j = 0; j < source.titles.length; j++) {
            var title = source.titles[j];
            if (manifestExcluded(title.path, profile.omitted_paths)) continue;
            var expected = target.titles[j];
            if (!expected) continue;
            var layer = findLayer(doc, title.path);
            var actual = manifestRect(layer);
            manifestMoveLayer(layer, expected.rect[1] - actual[1]);
        }
    }
    var stretches = profile.stretch_paths || [];
    for (i = 0; i < stretches.length; i++) {
        var stretch = stretches[i];
        var module = geometry.modules[stretch.role];
        if (!module) continue;
        manifestResizeBackground(findLayer(doc, stretch.path), module.height_delta || 0);
    }
}

function manifestAssertOldImagesCleared(doc, profile) {
    for (var i = 0; i < profile.original_images.length; i++) {
        if (manifestResolvePaths(doc, profile.original_images[i].path).length) {
            throw new Error("母版旧商品图未清理：" + profile.original_images[i].path.join(" / "));
        }
    }
}

function manifestDecorationsVisibility(doc, job, verify) {
    var decorations = job.profile.decorations || [];
    var hidden = job.hidden_decorations || [];
    for (var i = 0; i < decorations.length; i++) {
        var entry = decorations[i];
        var path = null;
        for (var j = 0; j < manifestDecorationPaths.length; j++) {
            var candidate = manifestDecorationPaths[j];
            if (entry.id === manifestDecorationId(candidate) &&
                manifestJson(entry.path) === manifestJson(candidate)) path = candidate;
        }
        if (!path) continue;
        var matches = manifestResolvePaths(doc, path);
        if (matches.length !== 1) throw new Error("未定位母版绿线装饰：" + path.join(" / "));
        var remove = false;
        for (j = 0; j < hidden.length; j++) if (hidden[j] === entry.id) remove = true;
        if (verify) {
            var omittedByLayout = false;
            for (j = 0; j < job.profile.modules.length; j++) {
                var source = job.profile.modules[j];
                var target = job.geometry.modules[source.role];
                var paths = source.move_paths || (source.path ? [source.path] : []);
                if (target && !target.visible && manifestExcluded(path, paths)) omittedByLayout = true;
            }
            if (manifestVisiblePath(doc, path) !== (!remove && !omittedByLayout)) {
                throw new Error("绿线装饰显示状态核验失败：" + path.join(" / "));
            }
        } else if (remove) {
            // Retain the native shape in the editable output so Photoshop can
            // restore it later. The source master is never saved by this job.
            matches[0].visible = false;
        }
    }
}

function manifestRenderFields(doc, job, fonts) {
    var module = job.geometry.modules.product;
    var parent = findLayer(doc, manifestFindModule(job.profile, "product").path);
    var names = [];
    for (var i = 0; i < job.products.length; i++) names.push(job.products[i].label);
    for (var field in job.profile.fields) {
        var binding = job.profile.fields[field];
        var rect = manifestShiftRect(binding.rect, module.delta_y || 0);
        if (binding.generated && binding.label_rect) {
            manifestNativeText(doc, parent, "字段名 · " + field, field,
                manifestShiftRect(binding.label_rect, module.delta_y || 0),
                {font: fonts.cn.postScriptName, size_px: 28, color: workbenchInk, align: "left"}, fonts);
        }
        var value = field === "颜色" ? names.join("/") : job.info[field];
        manifestNativeText(doc, parent, "当前商品 · " + field, value || "", rect, binding.style, fonts);
    }
}

function manifestRenderProductAttributes(doc, job, verify) {
    var attributes = job.profile.product_attributes;
    if (!attributes) return false;
    var group = findLayer(doc, attributes.path);
    var values = job.product_attributes;
    var fit = attributes.fit;
    if (verify) {
        var pill = findLayer(group, [fit.shapes[1]]);
        for (var i = 0; i < fit.options.length; i++) {
            var option = fit.options[i];
            var fitText = findLayer(group, [option.value]);
            if (!group.visible || !fitText.visible || fitText.kind !== LayerKind.TEXT ||
                fitText.textItem.contents !== option.value) throw new Error("STEP1 版型文字核验失败");
            if (option.value === values["版型"] &&
                (!pill.visible || Math.abs(box(pill)[0] - fit.pill_left - option.dx) > 2)) {
                throw new Error("STEP1 版型选中状态核验失败");
            }
        }
    } else {
        setManifestFit(group, fit, values["版型"]);
    }
    for (var field in attributes.fields) {
        var layer = findLayer(group, attributes.fields[field].path);
        if (!layer.visible || layer.kind !== LayerKind.TEXT) throw new Error("STEP1 缺少可编辑文字：" + field);
        var value = values[field];
        if (verify) {
            if (layer.textItem.contents !== value) throw new Error("STEP1 属性文字核验失败：" + field);
        } else if (layer.textItem.contents !== value) {
            var before = box(layer);
            layer.textItem.contents = value;
            var after = box(layer);
            var dx = (before[0] + before[2] - after[0] - after[2]) / 2;
            if (dx) layer.translate(UnitValue(dx, "px"), UnitValue(0, "px"));
        }
    }
    return true;
}

function manifestRenderColors(doc, job, fonts) {
    var source = manifestFindModule(job.profile, "colors");
    var parent = findLayer(doc, source.path);
    var style = job.profile.colors.prototype.style;
    var targetHeight = Infinity;
    for (var itemIndex = 0; itemIndex < job.geometry.colors.items.length; itemIndex++) {
        var layoutItem = job.geometry.colors.items[itemIndex];
        var candidate = job.products[layoutItem.index];
        if (!candidate || !candidate.visible_bounds) throw new Error("商品图缺少可见主体范围");
        var bounds = candidate.visible_bounds;
        var width = bounds[2] - bounds[0];
        var height = bounds[3] - bounds[1];
        if (width <= 0 || height <= 0) throw new Error("商品图可见主体范围无效");
        var area = layoutItem.image_rect;
        targetHeight = Math.min(targetHeight, area[3], area[2] * height / width);
    }
    for (var i = 0; i < job.geometry.colors.items.length; i++) {
        var slot = job.geometry.colors.items[i];
        var product = job.products[slot.index];
        if (!product) throw new Error("选色布局缺少对应商品图");
        var visibleHeight = product.visible_bounds[3] - product.visible_bounds[1];
        workbenchPicture(doc, parent, product, "当前色图 · " + product.label, slot.image_rect, null, null, targetHeight / visibleHeight);
        manifestNativeText(doc, parent, "当前色名 · " + product.label, product.label, slot.label_rect,
            {font: style.font, size_px: style.size_px, color: style.color, align: "center"}, fonts);
    }
}

function manifestRenderTables(doc, job, fonts) {
    for (var i = 0; i < job.profile.modules.length; i++) {
        var source = job.profile.modules[i];
        if (!source.table) continue;
        var resolved = job.geometry.tables[source.table.key];
        if (!resolved || !job.geometry.modules[source.role].visible) continue;
        var parent = findLayer(doc, source.table.parent_path || source.path);
        var table = parent.layerSets.add();
        table.name = source.table.key + "（当前数据）";
        var region = resolved.region;
        var base;
        if (source.table.cover_rect) {
            var dy = job.geometry.modules[source.role].delta_y || 0;
            var cover = manifestShiftRect(source.table.cover_rect, dy);
            rectangle(doc, table, "覆盖原表格数据", cover[0], cover[1], cover[2], Math.max(cover[3], resolved.plan.height), [255, 255, 255], 0);
        }
        if (source.table.base_path) {
            base = findLayer(doc, source.table.base_path);
            base.move(table, ElementPlacement.INSIDE);
        } else {
            base = rectangle(doc, table, "母版表格容器", region[0], region[1], region[2], region[3], [255, 255, 255], 12);
        }
        base.name = "母版表底";
        var bounds = box(base);
        if (Math.abs(bounds[3] - bounds[1] - resolved.plan.height) > 0.5) {
            base.resize(100, 100 * resolved.plan.height / (bounds[3] - bounds[1]), AnchorPosition.TOPCENTER);
            bounds = box(base);
        }
        base.translate(UnitValue(region[0] - bounds[0], "px"), UnitValue(region[1] - bounds[1], "px"));
        drawPantsDetailTable(doc, table, base, job.tables[source.table.key],
            [region[0], region[1], region[0] + region[2], region[1] + region[3]], resolved.plan, resolved.spec, fonts);
    }
}

function manifestGeneratedHero(doc, job, fonts) {
    var source = manifestFindModule(job.profile, "hero");
    var target = job.geometry.modules.hero;
    if (!source || !target || !target.visible) return null;
    var group = doc.layerSets.add();
    group.name = "当前主视觉";
    rectangle(doc, group, "母版主视觉底色", target.rect[0], target.rect[1], target.rect[2], target.rect[3],
              source.fill || [235, 245, 242], source.radius || 0);
    var names = [];
    for (var i = 0; i < job.products.length; i++) names.push(job.products[i].label);
    var texts = source.dynamic_texts || [];
    for (i = 0; i < texts.length; i++) {
        var item = texts[i];
        var value = item.field === "colors" ? names.join(item.separator || "/") : job.info[item.field];
        manifestNativeText(doc, group, "主视觉字段 · " + item.field, (item.prefix || "") + (value || ""),
                           manifestShiftRect(item.rect, target.delta_y || 0), item.style, fonts);
    }
    return group;
}

function manifestSlotFrame(doc, job, key, heroGroup) {
    var source = job.profile.view_slots[key];
    var target = job.geometry.view_slots[key];
    var role = manifestRoleForSlot(key);
    var module = manifestFindModule(job.profile, role);
    var parent = role === "hero" ? heroGroup : findLayer(doc, module.path);
    var frame;
    if (source.path) {
        frame = findLayer(doc, source.path);
    } else if (source.prototype_path) {
        frame = findLayer(doc, source.prototype_path).duplicate(parent, ElementPlacement.INSIDE);
        frame.name = "当前图框 · " + key;
    } else {
        frame = rectangle(doc, parent, "当前图框 · " + key, target.rect[0], target.rect[1], target.rect[2], target.rect[3],
                          [255, 255, 255], source.radius || 0);
    }
    frame.visible = true;
    var b = box(frame);
    frame.translate(UnitValue(target.rect[0] - b[0], "px"), UnitValue(target.rect[1] - b[1], "px"));
    return {frame: frame, parent: frame.parent};
}

function manifestRenderMeasurement(doc, job, source, target) {
    var original = findLayer(doc, source.path);
    if (!target || !target.visible) {
        original.visible = false;
        return 0;
    }
    var y = box(original)[1];
    manifestMoveLayer(original, target.rect[1] - Math.floor(y));
    if (!job.measurement) return 0;
    var layer = workbenchPicture(doc, original.parent, job.measurement, "当前照片 · measurement",
                                 target.rect, null, "measurement");
    layer.move(original, ElementPlacement.PLACEBEFORE);
    original.visible = false;
    return 1;
}

function manifestRenderSizeNote(doc, job, fonts) {
    var note = job.profile.size_note;
    var module = job.geometry.modules.size_table;
    if (!note || !module || !module.visible || job.size_note === null || job.size_note === undefined) return;
    hideManifestSizeNote(doc, job.profile);
    if (!job.size_note) return;
    var plan = job.geometry.size_note;
    if (!plan || !plan.rect) throw new Error("缺少当前尺码备注的版式");
    var first = findLayer(doc, note.lines[0].path);
    manifestNativeText(doc, first.parent, "当前尺码备注", job.size_note, plan.rect, note.style, fonts);
}

function manifestRenderViews(doc, job, heroGroup) {
    var count = 0;
    for (var key in job.profile.view_slots) {
        var source = job.profile.view_slots[key];
        var target = job.geometry.view_slots[key];
        if (key === "measurement") {
            count += manifestRenderMeasurement(doc, job, source, target);
            continue;
        }
        if (!target || !target.visible) {
            if (source.path) {
                var unused = manifestResolvePaths(doc, source.path);
                for (var i = 0; i < unused.length; i++) unused[i].visible = false;
            }
            continue;
        }
        var item = key === "hero" ? job.hero : key === "brand" ? job.brand : job.scenes[parseInt(key.split("_")[1], 10) - 1];
        if (!item) continue;
        var slot = manifestSlotFrame(doc, job, key, heroGroup);
        workbenchPicture(doc, slot.parent, item, "当前照片 · " + key, target.rect, slot.frame, key);
        count++;
    }
    return count;
}

function manifestClipSceneModule(doc, job) {
    var source = manifestFindModule(job.profile, "scenes");
    var target = job.geometry.modules.scenes;
    if (!source || !target || !target.visible) return;
    var group = findLayer(doc, source.path);
    var rect = target.rect;
    var savedChannels = doc.activeChannels;
    app.activeDocument = doc;
    doc.activeLayer = group;
    doc.selection.select([[rect[0], rect[1]], [rect[0] + rect[2], rect[1]],
                          [rect[0] + rect[2], rect[1] + rect[3]], [rect[0], rect[1] + rect[3]]]);
    try {
        var key = stringIDToTypeID;
        var reference = new ActionReference();
        reference.putProperty(key("property"), key("hasUserMask"));
        reference.putIdentifier(key("layer"), group.id);
        var descriptor = executeActionGet(reference);
        var hasMask = descriptor.hasKey(key("hasUserMask")) && descriptor.getBoolean(key("hasUserMask"));
        if (hasMask) {
            var select = new ActionDescriptor();
            var channel = new ActionReference();
            channel.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
            select.putReference(charIDToTypeID("null"), channel);
            executeAction(charIDToTypeID("slct"), select, DialogModes.NO);
            doc.selection.invert();
            doc.selection.fill(rgb([0, 0, 0]), ColorBlendMode.NORMAL, 100, false);
        } else {
            var create = new ActionDescriptor();
            create.putClass(charIDToTypeID("Nw  "), charIDToTypeID("Chnl"));
            var location = new ActionReference();
            location.putEnumerated(charIDToTypeID("Chnl"), charIDToTypeID("Chnl"), charIDToTypeID("Msk "));
            create.putReference(charIDToTypeID("At  "), location);
            create.putEnumerated(charIDToTypeID("Usng"), charIDToTypeID("UsrM"), charIDToTypeID("RvlS"));
            executeAction(charIDToTypeID("Mk  "), create, DialogModes.NO);
        }
    } finally {
        doc.selection.deselect();
        doc.activeChannels = savedChannels;
    }
}

function manifestSpacing(first, second, label) {
    if (!first || !second) return null;
    var gap = Math.max(second[0] - first[2], first[0] - second[2], second[1] - first[3], first[1] - second[3]);
    if (gap < 0) throw new Error(label + "在重开后的 PSB 中重叠（" + (-gap) + " px）");
    return gap;
}

function manifestVerify(doc, job, expectedPhotos) {
    manifestDecorationsVisibility(doc, job, true);
    var attributesEditable = manifestRenderProductAttributes(doc, job, true);
    var sizeBounds = {size_table: null, measurement: null, size_note: null};
    var sizeNoteEditable = false;
    var note = job.profile.size_note;
    var sizeTarget = job.geometry.modules.size_table;
    if (note && sizeTarget && sizeTarget.visible) {
        var originalNote = findLayer(doc, note.lines[0].path);
        var inherited = job.size_note === null || job.size_note === undefined;
        for (var n = 0; n < note.lines.length; n++) {
            var originalLine = findLayer(doc, note.lines[n].path);
            if (originalLine.visible !== inherited) {
                throw new Error("母版尺码备注显示状态核验失败");
            }
            if (inherited) {
                if (originalLine.kind !== LayerKind.TEXT) throw new Error("母版尺码备注不是可编辑文字");
                var lineBounds = box(originalLine);
                var combined = sizeBounds.size_note;
                sizeBounds.size_note = combined ? [Math.min(combined[0], lineBounds[0]), Math.min(combined[1], lineBounds[1]),
                    Math.max(combined[2], lineBounds[2]), Math.max(combined[3], lineBounds[3])] : lineBounds;
                sizeNoteEditable = true;
            }
        }
        if (!inherited && job.size_note) {
            var insertedNote = findLayer(originalNote.parent, ["当前尺码备注"]);
            if (!insertedNote.visible || insertedNote.kind !== LayerKind.TEXT ||
                insertedNote.textItem.contents.replace(/\r\n?/g, "\n") !== job.geometry.size_note.lines.join("\n")) {
                throw new Error("尺码备注未以可编辑文字保存");
            }
            sizeBounds.size_note = box(insertedNote);
            sizeNoteEditable = true;
        }
    }
    var measurement = job.profile.view_slots.measurement;
    if (measurement) {
        var nativeMeasurement = findLayer(doc, measurement.path);
        var measurementTarget = job.geometry.view_slots.measurement;
        var showOriginal = Boolean(measurementTarget && measurementTarget.visible && !job.measurement);
        if (nativeMeasurement.visible !== showOriginal) throw new Error("母版测量示意图显示状态核验失败");
        if (showOriginal) sizeBounds.measurement = box(nativeMeasurement);
        if (measurementTarget && measurementTarget.visible && job.measurement) {
            var insertedMeasurement = findLayer(nativeMeasurement.parent, ["当前照片 · measurement"]);
            var mb = box(insertedMeasurement);
            var mr = measurementTarget.rect;
            if (!insertedMeasurement.visible || insertedMeasurement.kind !== LayerKind.SMARTOBJECT || mb[0] < mr[0] - 2 || mb[1] < mr[1] - 2 ||
                mb[2] > mr[0] + mr[2] + 2 || mb[3] > mr[1] + mr[3] + 2) {
                throw new Error("尺码测量示意图未在母版图位完整嵌入");
            }
            sizeBounds.measurement = mb;
        }
    }
    var fieldsParent = findLayer(doc, manifestFindModule(job.profile, "product").path);
    var names = [];
    for (var i = 0; i < job.products.length; i++) names.push(job.products[i].label);
    for (var field in job.profile.fields) {
        var expected = field === "颜色" ? names.join("/") : job.info[field];
        var layer = findLayer(fieldsParent, ["当前商品 · " + field]);
        if (layer.kind !== LayerKind.TEXT || layer.textItem.contents.replace(/\r/g, "") !== expected) {
            throw new Error("商品字段与确认数据不符：" + field);
        }
    }
    var colors = findLayer(doc, manifestFindModule(job.profile, "colors").path);
    if (verifyEmbedded(colors, /^当前色图 · /) !== job.products.length) throw new Error("实际色图数量与商品颜色不符");
    for (i = 0; i < job.products.length; i++) {
        layer = findLayer(colors, ["当前色名 · " + job.products[i].label]);
        if (layer.textItem.contents.replace(/\r/g, "") !== job.products[i].label) throw new Error("色名与商品图对应错误");
    }
    if (verifyEmbedded(doc, /^当前照片 · /) !== expectedPhotos) throw new Error("实际照片图位数量不符");
    for (i = 0; i < job.profile.modules.length; i++) {
        var source = job.profile.modules[i];
        var target = job.geometry.modules[source.role];
        if (!target || !target.visible) continue;
        for (var j = 0; j < source.titles.length; j++) {
            var title = source.titles[j];
            if (manifestExcluded(title.path, job.profile.omitted_paths)) continue;
            if (title.static_only) continue;
            layer = findLayer(doc, title.path);
            if (layer.kind !== LayerKind.TEXT || layer.textItem.contents !== title.text) {
                throw new Error("母版原标题被改变：" + title.path.join(" / "));
            }
            var current = manifestStyle(layer, doc);
            if (current.font !== title.style.font || Math.abs(current.size_px - title.style.size_px) > 0.5) {
                throw new Error("母版原标题样式被改变：" + title.path.join(" / "));
            }
        }
        if (!source.table || !job.tables[source.table.key]) continue;
        var parent = findLayer(doc, source.table.parent_path || source.path);
        var table = findLayer(parent, [source.table.key + "（当前数据）"]);
        if (source.role === "size_table") sizeBounds.size_table = box(table);
        var matrix = job.tables[source.table.key];
        for (var r = 0; r < matrix.length; r++) {
            var row = findLayer(table, [r === 0 ? "表头" : "第 " + r + " 行"]);
            for (var c = 0; c < matrix[r].length; c++) {
                layer = findLayer(row, ["第 " + (c + 1) + " 列"]);
                if (layer.kind !== LayerKind.TEXT || layer.textItem.contents !== (matrix[r][c] || " ")) {
                    throw new Error("表格内容核验失败：" + source.table.key);
                }
            }
        }
    }
    var verification = {
        bounds_px: sizeBounds,
        clearance_px: {
            table_measurement: manifestSpacing(sizeBounds.size_table, sizeBounds.measurement, "尺码表和量体图"),
            measurement_note: manifestSpacing(sizeBounds.measurement, sizeBounds.size_note, "量体图和尺码备注"),
            table_note: manifestSpacing(sizeBounds.size_table, sizeBounds.size_note, "尺码表和尺码备注")
        },
        size_note_editable: sizeNoteEditable,
        product_attributes_editable: attributesEditable
    };
    var method = manifestFindModule(job.profile, "measurement_method");
    if (method && job.geometry.modules.measurement_method.visible) {
        var rectangles = [];
        for (var m = 0; m < method.move_paths.length; m++) {
            var methodLayer = findLayer(doc, method.move_paths[m]);
            if (methodLayer.visible) rectangles.push(manifestRect(methodLayer));
        }
        if (rectangles.length) {
            var methodRect = manifestUnion(rectangles);
            var methodBounds = [methodRect[0], methodRect[1], methodRect[0] + methodRect[2], methodRect[1] + methodRect[3]];
            verification.bounds_px.measurement_method = methodBounds;
            verification.clearance_px.table_method = manifestSpacing(sizeBounds.size_table, methodBounds, "尺码表和测量方法");
            verification.clearance_px.note_method = manifestSpacing(sizeBounds.size_note, methodBounds, "尺码备注和测量方法");
        }
    }
    return verification;
}

var manifestBuildContext = null;

function manifestBuildSuspendedDocument() {
    if (!manifestBuildContext) throw new Error("缺少套版构建上下文");
    var context = manifestBuildContext;
    var doc = context.doc;
    var job = context.job;
    var fonts = context.fonts;
    context.stage = "清理原商品数据";
    clearManifestData(doc, job.profile, false);
    manifestAssertOldImagesCleared(doc, job.profile);
    context.stage = "应用绿线装饰设置";
    manifestDecorationsVisibility(doc, job, false);
    context.stage = "应用统一布局";
    applyManifestGeometry(doc, job);
    context.stage = "写入商品资料与颜色";
    manifestRenderFields(doc, job, fonts);
    manifestRenderProductAttributes(doc, job, false);
    manifestRenderColors(doc, job, fonts);
    context.stage = "替换表格内芯";
    manifestRenderTables(doc, job, fonts);
    context.stage = "应用尺码备注";
    manifestRenderSizeNote(doc, job, fonts);
    context.stage = "应用照片取景";
    var hero = manifestGeneratedHero(doc, job, fonts);
    context.photoCount = manifestRenderViews(doc, job, hero);
    doc.resizeCanvas(UnitValue(job.geometry.canvas.width, "px"), UnitValue(job.geometry.canvas.height, "px"), AnchorPosition.TOPCENTER);
    manifestClipSceneModule(doc, job);
}

function runManifestWorkbench(job) {
    var dialogs = app.displayDialogs;
    var units = app.preferences.rulerUnits;
    var prior = app.documents.length ? app.activeDocument : null;
    var doc, preview;
    var stage = "打开母版";
    workbenchActiveJob = job;
    try {
        app.displayDialogs = DialogModes.NO;
        app.preferences.rulerUnits = Units.PIXELS;
        var fonts = loadDetailMixedFonts();
        doc = app.open(new File(job.template));
        var photoCount = 0;
        manifestBuildContext = {doc: doc, job: job, fonts: fonts, photoCount: 0, stage: "构建套版"};
        try {
            doc.suspendHistory("工作台生成详情页", "manifestBuildSuspendedDocument()");
            photoCount = manifestBuildContext.photoCount;
        } catch (buildError) {
            stage = manifestBuildContext.stage;
            throw buildError;
        } finally {
            manifestBuildContext = null;
        }
        stage = "保存并重开源文件";
        saveDetailPsb(new File(job.output));
        doc.close(SaveOptions.DONOTSAVECHANGES);
        doc = app.open(new File(job.output));
        stage = "核验原标题、颜色、表格和尺码区间距";
        var layoutVerification = manifestVerify(doc, job, photoCount);
        stage = "导出整页预览";
        preview = doc.duplicate("详情页工作台预览", true);
        preview.flatten();
        preview.resizeImage(UnitValue(500, "px"), null, null, ResampleMethod.BICUBICSHARPER);
        var options = new JPEGSaveOptions();
        options.quality = 9;
        preview.saveAs(new File(job.preview), options, true, Extension.LOWERCASE);
        if (job.layout_verification) manifestWrite(job.layout_verification, layoutVerification);
    } catch (error) {
        throw new Error(stage + "失败，原第 " + error.line + " 行：" + error.message);
    } finally {
        if (preview) { try { preview.close(SaveOptions.DONOTSAVECHANGES); } catch (previewError) {} }
        if (doc) { try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (closeError) {} }
        app.preferences.rulerUnits = units;
        app.displayDialogs = dialogs;
        workbenchActiveJob = null;
        if (prior) { try { app.activeDocument = prior; } catch (priorError) {} }
    }
    var marker = new File(job.completed);
    if (!marker.open("w")) throw new Error("无法写入详情页核验记录");
    marker.write(String(job.geometry.canvas.height));
    marker.close();
}
