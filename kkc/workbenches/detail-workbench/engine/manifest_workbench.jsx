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
        if (!module || !module.visible) continue;
        manifestResizeBackground(findLayer(doc, stretch.path), module.height_delta || 0);
    }
}

function manifestApplyCompactHelperGeometry(doc, job) {
    if (!manifestCompactEnabled(job)) return;
    var target = job.geometry.modules.size_table;
    var helpers = target && target.visible && target.helper_layout;
    if (!helpers) return;
    var measurement = job.profile.view_slots.measurement;
    if (measurement && helpers.measurement_rect) {
        var illustration = findLayer(doc, measurement.path);
        manifestMoveLayer(illustration, helpers.measurement_rect[1] - manifestRect(illustration)[1]);
    }
    // Apply the same targets for a skipped table's helpers and for a valid
    // short table's following note. Replacing text uses geometry.size_note;
    // inherited native text moves to those identical targets here.
    var lines = helpers.note_lines || [];
    for (var i = 0; i < lines.length; i++) {
        var layer = findLayer(doc, lines[i].path);
        manifestMoveLayer(layer, lines[i].rect[1] - manifestRect(layer)[1]);
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
        if (verify && !matches.length && manifestCompactPathWasRemoved(job, path)) continue;
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

function manifestTableIsRendered(job, source) {
    if (!source.table) return false;
    var target = job.geometry.modules[source.role];
    return Boolean(target && target.visible && target.table_visible !== false &&
        job.geometry.tables[source.table.key] && job.tables[source.table.key]);
}

function manifestTableLayoutError(key, message) {
    return new Error("[TABLE_LAYOUT:" + key + "] " + message);
}

function manifestKnownTableLayoutError(error) {
    var message = String(error.message || error);
    return message.indexOf("列内容超出本区可读宽度") >= 0 ||
        message.indexOf("列文字过密") >= 0 || message.indexOf("行文字超出行高") >= 0 ||
        message.indexOf("表格文字过宽：") >= 0 ||
        message.indexOf("表格单元格请填写单行内容") >= 0;
}

function manifestTableProtectedPaths(job) {
    var paths = [];
    var measurement = job.profile.view_slots.measurement;
    if (measurement && measurement.path) paths.push(measurement.path);
    var note = job.profile.size_note;
    if (note) for (var n = 0; n < note.lines.length; n++) paths.push(note.lines[n].path);
    return paths;
}

function manifestTableBaseIsProtected(job, path) {
    var retained = manifestTableProtectedPaths(job);
    for (var i = 0; i < retained.length; i++) {
        if (manifestPrefix(retained[i], path) || manifestPrefix(path, retained[i])) return true;
    }
    return false;
}

function manifestClearOmittedTable(doc, job, source) {
    var target = job.geometry.modules[source.role];
    var key = source.table.key;
    if (source.table.base_path && !manifestTableBaseIsProtected(job, source.table.base_path)) {
        var bases = manifestResolvePaths(doc, source.table.base_path);
        for (var b = 0; b < bases.length; b++) bases[b].visible = false;
    }
    // Shared sizing groups can also contain the measurement illustration and
    // editable note. Only the agreed table rectangles are cleared in that case.
    var omission = job.geometry.omitted_tables && job.geometry.omitted_tables[key];
    if (!target || !target.visible || !omission || !omission.clear_rects.length) return;
    var parent = findLayer(doc, source.table.parent_path || source.path);
    var cover = parent.layerSets.add();
    cover.name = "表格留白 · " + key;
    for (var i = 0; i < omission.clear_rects.length; i++) {
        var rect = omission.clear_rects[i];
        rectangle(doc, cover, "清空原表格 " + (i + 1), rect[0], rect[1], rect[2], rect[3], [255, 255, 255], 0);
    }
}

function manifestCheckRenderedTable(doc, table, matrix, resolved, key) {
    var region = resolved.region;
    var plan = resolved.plan;
    for (var r = 0; r < matrix.length; r++) {
        var row = findLayer(table, [r === 0 ? "表头" : "第 " + r + " 行"]);
        var left = region[0];
        var top = r === 0 ? region[1] : region[1] + plan.header + (r - 1) * plan.row;
        var height = r === 0 ? plan.header : plan.row;
        for (var c = 0; c < matrix[r].length; c++) {
            var cell = findLayer(row, ["第 " + (c + 1) + " 列"]);
            if (cell.kind !== LayerKind.TEXT || cell.textItem.contents !== (matrix[r][c] || " ")) {
                throw new Error("表格内容核验失败：" + key + " 第 " + (r + 1) + " 行，第 " + (c + 1) + " 列");
            }
            if (/\S/.test(String(matrix[r][c] || ""))) {
                var actual = box(cell);
                if (cell.textItem.size.as("pt") * doc.resolution / 72 < 15.5 ||
                    actual[0] < left - 1 || actual[2] > left + plan.widths[c] + 1 ||
                    actual[1] < top + 1 || actual[3] > top + height - 1) {
                    throw manifestTableLayoutError(key, "第 " + (r + 1) + " 行，第 " + (c + 1) + " 列文字超出可读单元格范围。");
                }
            }
            left += plan.widths[c];
        }
    }
}

function manifestVerifyOmittedTable(doc, job, source) {
    var key = source.table.key;
    var target = job.geometry.modules[source.role];
    var currentPath = (source.table.parent_path || source.path).concat([key + "（当前数据）"]);
    if (manifestResolvePaths(doc, currentPath).length) throw new Error("已跳过的表格仍含当前数据：" + key);
    var oldPaths = source.table.data_paths || [];
    for (var p = 0; p < oldPaths.length; p++) {
        if (manifestResolvePaths(doc, oldPaths[p]).length) throw new Error("已跳过的表格仍含母版旧数据：" + key);
    }
    if (source.table.base_path && !manifestTableBaseIsProtected(job, source.table.base_path) &&
        manifestVisiblePath(doc, source.table.base_path)) throw new Error("已跳过的表格底板仍可见：" + key);
    var status = job.geometry.table_status && job.geometry.table_status[key];
    var result = {state: status ? status.state : "absent", reason: status ? status.reason : "",
        emitted: false, old_data_removed: true, matrix: null, bounds_px: null};
    var omission = job.geometry.omitted_tables && job.geometry.omitted_tables[key];
    result.clear_rects = omission ? omission.clear_rects : [];
    if (target && target.visible && omission && omission.clear_rects.length) {
        var parent = findLayer(doc, source.table.parent_path || source.path);
        var cover = findLayer(parent, ["表格留白 · " + key]);
        if (!cover.visible) throw new Error("已跳过表格的留白未显示：" + key);
        for (var c = 0; c < omission.clear_rects.length; c++) {
            var layer = findLayer(cover, ["清空原表格 " + (c + 1)]);
            var actual = box(layer);
            var rect = omission.clear_rects[c];
            if (!layer.visible || Math.abs(actual[0] - rect[0]) > 1 || Math.abs(actual[1] - rect[1]) > 1 ||
                Math.abs(actual[2] - rect[0] - rect[2]) > 1 || Math.abs(actual[3] - rect[1] - rect[3]) > 1) {
                throw new Error("已跳过表格的留白位置核验失败：" + key);
            }
        }
    }
    return result;
}

function manifestRenderTables(doc, job, fonts) {
    for (var i = 0; i < job.profile.modules.length; i++) {
        var source = job.profile.modules[i];
        if (!source.table) continue;
        var resolved = job.geometry.tables[source.table.key];
        if (!manifestTableIsRendered(job, source)) {
            manifestClearOmittedTable(doc, job, source);
            continue;
        }
        var parent = findLayer(doc, source.table.parent_path || source.path);
        var table = parent.layerSets.add();
        table.name = source.table.key + "（当前数据）";
        var region = resolved.region;
        var base;
        if (source.table.cover_rect) {
            var dy = job.geometry.modules[source.role].delta_y || 0;
            var cover = resolved.cover_rect || manifestShiftRect(source.table.cover_rect, dy);
            var coverHeight = resolved.cover_rect ? cover[3] : Math.max(cover[3], resolved.plan.height);
            if (coverHeight > 0) rectangle(doc, table, "覆盖原表格数据", cover[0], cover[1], cover[2], coverHeight, [255, 255, 255], 0);
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
        try {
            drawPantsDetailTable(doc, table, base, job.tables[source.table.key],
                [region[0], region[1], region[0] + region[2], region[1] + region[3]], resolved.plan, resolved.spec, fonts);
        } catch (tableError) {
            if (manifestKnownTableLayoutError(tableError)) {
                throw manifestTableLayoutError(source.table.key, tableError.message);
            }
            throw tableError;
        }
        manifestCheckRenderedTable(doc, table, job.tables[source.table.key], resolved, source.table.key);
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
        // Photoshop 2020's ExtendScript can resolve the nested conditional here
        // through the brand branch even for "hero". Keep these choices explicit.
        var item;
        if (key === "hero") item = job.hero;
        else if (key === "brand") item = job.brand;
        else item = job.scenes[parseInt(key.split("_")[1], 10) - 1];
        if (!item) continue;
        var slot = manifestSlotFrame(doc, job, key, heroGroup);
        workbenchPicture(doc, slot.parent, item, "当前照片 · " + key, target.rect, slot.frame, key);
        count++;
    }
    return count;
}

function manifestVerifyPhotoSlots(doc, job) {
    var verified = [];
    for (var key in job.profile.view_slots) {
        var source = job.profile.view_slots[key];
        var target = job.geometry.view_slots[key];
        if (!target || !target.visible) continue;
        var item = null;
        if (key === "measurement") item = job.measurement;
        else if (key === "hero") item = job.hero;
        else if (key === "brand") item = job.brand;
        else if (key.indexOf("scene_") === 0) item = job.scenes[parseInt(key.split("_")[1], 10) - 1];
        // An unbound measurement inherits its native illustration instead.
        if (key === "measurement" && !item) continue;
        if (!item) throw new Error("可见照片图位缺少已确认素材：" + key);
        var parentPath;
        if (source.path) parentPath = source.path.slice(0, -1);
        else if (key === "hero") parentPath = ["当前主视觉"];
        else parentPath = manifestFindModule(job.profile, manifestRoleForSlot(key)).path;
        var path = parentPath.concat(["当前照片 · " + key]);
        var layer = findLayer(doc, path);
        if (layer.kind !== LayerKind.SMARTOBJECT || !manifestVisiblePath(doc, path) || layer.opacity <= 0) {
            throw new Error("重开后照片图位不可见或不是智能对象：" + key);
        }
        var rect = target.rect, bounds = box(layer);
        if (bounds[2] <= rect[0] || bounds[0] >= rect[0] + rect[2] ||
                bounds[3] <= rect[1] || bounds[1] >= rect[1] + rect[3]) {
            throw new Error("重开后照片没有落入对应图框：" + key);
        }
        if (key !== "measurement") {
            var framePath;
            if (source.path) framePath = source.path;
            else framePath = parentPath.concat(["当前图框 · " + key]);
            if (!manifestVisiblePath(doc, framePath) || !layer.grouped) {
                throw new Error("重开后照片的图框不可见或剪贴关系丢失：" + key);
            }
        }
        verified.push({slot: key, path: path, visible: true, embedded: true,
                       bounds_px: bounds, frame: rect.slice()});
    }
    return verified;
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

function manifestCompactEnabled(job) {
    return job.profile.compact_version === 1;
}

function manifestCompactPathWasRemoved(job, path) {
    var removed = job.output_pruned_paths || [];
    for (var i = 0; i < removed.length; i++) if (manifestPrefix(path, removed[i])) return true;
    return false;
}

function manifestCompactPathsRelated(path, protectedPaths) {
    for (var i = 0; i < protectedPaths.length; i++) {
        if (manifestPrefix(path, protectedPaths[i]) || manifestPrefix(protectedPaths[i], path)) return true;
    }
    return false;
}

function manifestCompactIsRequiredAncestor(path, protectedPaths) {
    for (var i = 0; i < protectedPaths.length; i++) if (manifestPrefix(protectedPaths[i], path)) return true;
    return false;
}

function manifestCompactRemovePath(doc, job, path) {
    if (!path || !path.length) return;
    var matches = manifestResolvePaths(doc, path);
    if (!matches.length) return;
    for (var i = matches.length - 1; i >= 0; i--) matches[i].remove();
    job.output_pruned_paths.push(path.slice());
}

function manifestCompactProtectedPaths(job) {
    var paths = [];
    for (var i = 0; i < job.profile.modules.length; i++) {
        var module = job.profile.modules[i];
        var target = job.geometry.modules[module.role];
        if (target && target.visible) paths = paths.concat(module.move_paths || (module.path ? [module.path] : []));
    }
    var measurement = job.profile.view_slots.measurement;
    if (measurement && job.geometry.view_slots.measurement && job.geometry.view_slots.measurement.visible) paths.push(measurement.path);
    var note = job.profile.size_note;
    if (note && job.geometry.modules.size_table && job.geometry.modules.size_table.visible) {
        for (i = 0; i < note.lines.length; i++) paths.push(note.lines[i].path);
    }
    if (job.profile.product_attributes) paths.push(job.profile.product_attributes.path);
    return paths;
}

function manifestCompactSceneTail(parent, path, bottom, protectedPaths, doc, job) {
    if (parent.typename !== "LayerSet") return;
    for (var i = parent.layers.length - 1; i >= 0; i--) {
        if (i >= parent.layers.length) continue;
        var layer = parent.layers[i];
        var childPath = path.concat([layer.name]);
        var retained = manifestCompactPathsRelated(childPath, protectedPaths) || /^当前照片 · /.test(layer.name);
        if (!retained) {
            var bounds = box(layer);
            if (bounds[1] >= bottom - .5) {
                manifestCompactRemovePath(doc, job, childPath);
                continue;
            }
        }
        if (layer.typename === "LayerSet") {
            manifestCompactSceneTail(layer, childPath, bottom, protectedPaths, doc, job);
            if (!layer.layers.length && !retained) manifestCompactRemovePath(doc, job, childPath);
        }
    }
}

function manifestCompactRemoveEmptyGroups(parent, path, protectedPaths, doc, job) {
    for (var i = parent.layers.length - 1; i >= 0; i--) {
        if (i >= parent.layers.length) continue;
        var layer = parent.layers[i];
        if (layer.typename !== "LayerSet") continue;
        var childPath = path.concat([layer.name]);
        manifestCompactRemoveEmptyGroups(layer, childPath, protectedPaths, doc, job);
        if (!layer.layers.length && !manifestCompactIsRequiredAncestor(childPath, protectedPaths)) {
            manifestCompactRemovePath(doc, job, childPath);
        }
    }
}

function manifestPruneCompactOutput(doc, job) {
    if (!manifestCompactEnabled(job)) return;
    job.output_pruned_paths = [];
    var protectedPaths = manifestCompactProtectedPaths(job);
    var i, p, module, target, paths;
    for (i = 0; i < job.profile.modules.length; i++) {
        module = job.profile.modules[i];
        target = job.geometry.modules[module.role];
        if (target && target.visible) continue;
        paths = module.move_paths || (module.path ? [module.path] : []);
        for (p = 0; p < paths.length; p++) {
            if (!manifestCompactPathsRelated(paths[p], protectedPaths)) manifestCompactRemovePath(doc, job, paths[p]);
        }
    }
    // The original data has already been deleted. Do not leave independent old
    // table containers, unused picture frames, or off-page scene groups hidden.
    for (i = 0; i < job.profile.modules.length; i++) {
        module = job.profile.modules[i];
        if (module.table && !manifestTableIsRendered(job, module) && module.table.base_path &&
                !manifestTableBaseIsProtected(job, module.table.base_path)) {
            manifestCompactRemovePath(doc, job, module.table.base_path);
        }
    }
    var activeScenePaths = [];
    for (var key in job.profile.view_slots) {
        if (key.indexOf("scene_") !== 0) continue;
        var slot = job.profile.view_slots[key];
        target = job.geometry.view_slots[key];
        if (slot.path && target && target.visible) activeScenePaths.push(slot.path);
    }
    for (key in job.profile.view_slots) {
        if (key.indexOf("scene_") !== 0) continue;
        slot = job.profile.view_slots[key];
        target = job.geometry.view_slots[key];
        if (slot.path && (!target || !target.visible) && !manifestCompactPathsRelated(slot.path, activeScenePaths)) {
            manifestCompactRemovePath(doc, job, slot.path);
        }
    }
    var scene = manifestFindModule(job.profile, "scenes");
    target = job.geometry.modules.scenes;
    if (scene && target && target.visible && scene.path) {
        var sceneRoots = manifestResolvePaths(doc, scene.path);
        for (i = 0; i < sceneRoots.length; i++) {
            manifestCompactSceneTail(sceneRoots[i], scene.path, target.rect[1] + target.rect[3], activeScenePaths, doc, job);
        }
    }
    var note = job.profile.size_note;
    if (note && job.size_note !== null && job.size_note !== undefined) {
        for (i = 0; i < note.lines.length; i++) manifestCompactRemovePath(doc, job, note.lines[i].path);
    }
    var measurement = job.profile.view_slots.measurement;
    if (measurement && job.measurement) manifestCompactRemovePath(doc, job, measurement.path);
    manifestCompactRemoveEmptyGroups(doc, [], protectedPaths, doc, job);
}

function manifestVerifyCompactContent(doc, job) {
    if (!manifestCompactEnabled(job)) return null;
    var allowed = ["header", "hero", "product", "colors", "size_table", "quick_size", "try_on", "measurement_method", "scenes"];
    var roles = [];
    var intervals = [];
    for (var role in job.geometry.modules) {
        var target = job.geometry.modules[role];
        if (!target.visible) continue;
        var accepted = false;
        for (var a = 0; a < allowed.length; a++) if (allowed[a] === role) accepted = true;
        if (!accepted) throw new Error("精简成品仍包含未保留模块：" + role);
        roles.push(role);
        intervals.push([target.rect[1], target.rect[1] + target.rect[3]]);
    }
    var removed = (job.output_pruned_paths || []).slice();
    var summary = job.profile.compact_summary || {};
    removed = removed.concat(summary.removed_paths || []);
    for (var i = 0; i < removed.length; i++) {
        if (manifestResolvePaths(doc, removed[i]).length) throw new Error("精简成品仍含已排除图层：" + removed[i].join(" / "));
    }
    intervals.sort(function (a, b) { return a[0] - b[0]; });
    var first = intervals.length ? intervals[0][0] : 0;
    var bottom = intervals.length ? intervals[0][1] : 0;
    var maxGap = 0;
    for (i = 1; i < intervals.length; i++) {
        maxGap = Math.max(maxGap, intervals[i][0] - bottom);
        bottom = Math.max(bottom, intervals[i][1]);
    }
    var height = doc.height.as("px");
    if (Math.abs(height - job.geometry.canvas.height) > .5) throw new Error("精简成品画布高度与预览不一致");
    if (first > 80 || maxGap > 80.5 || height - bottom > 80.5 || bottom > height + .5) {
        throw new Error("精简成品存在超出约定的空白：页首 " + first + "、模块间 " + maxGap + "、页尾 " + (height - bottom) + " px");
    }
    return {version: 1, kept_roles: roles, removed_layer_paths: removed,
        actual_canvas_height: height, planned_canvas_height: job.geometry.canvas.height,
        first_module_top: first, max_inter_module_gap: maxGap, bottom_margin: height - bottom,
        no_excluded_layers: true};
}

function manifestSpacing(first, second, label) {
    if (!first || !second) return null;
    var gap = Math.max(second[0] - first[2], first[0] - second[2], second[1] - first[3], first[1] - second[3]);
    if (gap < 0) throw new Error(label + "在重开后的 PSB 中重叠（" + (-gap) + " px）");
    return gap;
}

function manifestTableSpacing(first, second, label, key) {
    try {
        return manifestSpacing(first, second, label);
    } catch (error) {
        throw manifestTableLayoutError(key, error.message);
    }
}

function manifestVerify(doc, job, expectedPhotos) {
    manifestDecorationsVisibility(doc, job, true);
    var attributesEditable = manifestRenderProductAttributes(doc, job, true);
    var sizeBounds = {size_table: null, measurement: null, size_note: null};
    var sizeNoteEditable = false;
    var tableVerification = {};
    var statuses = job.geometry.table_status || {};
    for (var tableKey in statuses) {
        tableVerification[tableKey] = {state: statuses[tableKey].state, reason: statuses[tableKey].reason,
            emitted: false, matrix: null, bounds_px: null};
    }
    var note = job.profile.size_note;
    var sizeTarget = job.geometry.modules.size_table;
    if (note && sizeTarget && sizeTarget.visible) {
        var inherited = job.size_note === null || job.size_note === undefined;
        var originalNote = null;
        if (!manifestCompactEnabled(job) || inherited) originalNote = findLayer(doc, note.lines[0].path);
        for (var n = 0; n < note.lines.length; n++) {
            if (manifestCompactEnabled(job) && !inherited) {
                if (manifestResolvePaths(doc, note.lines[n].path).length) throw new Error("成品仍含替换前的尺码备注");
                continue;
            }
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
            var noteParent = originalNote ? originalNote.parent : findLayer(doc, note.lines[0].path.slice(0, -1));
            var insertedNote = findLayer(noteParent, ["当前尺码备注"]);
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
        var measurementTarget = job.geometry.view_slots.measurement;
        var showOriginal = Boolean(measurementTarget && measurementTarget.visible && !job.measurement);
        var measurementParent;
        if (manifestCompactEnabled(job) && job.measurement) {
            if (manifestResolvePaths(doc, measurement.path).length) throw new Error("成品仍含替换前的测量示意图");
            if (measurementTarget && measurementTarget.visible) measurementParent = findLayer(doc, measurement.path.slice(0, -1));
        } else {
            var nativeMeasurement = findLayer(doc, measurement.path);
            measurementParent = nativeMeasurement.parent;
            if (nativeMeasurement.visible !== showOriginal) throw new Error("母版测量示意图显示状态核验失败");
            if (showOriginal) sizeBounds.measurement = box(nativeMeasurement);
        }
        if (measurementTarget && measurementTarget.visible && job.measurement) {
            var insertedMeasurement = findLayer(measurementParent, ["当前照片 · measurement"]);
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
    var photoSlots = manifestVerifyPhotoSlots(doc, job);
    if (expectedPhotos !== photoSlots.length || verifyEmbedded(doc, /^当前照片 · /) !== photoSlots.length) {
        throw new Error("实际照片图位数量与已确认绑定不符");
    }
    for (i = 0; i < job.profile.modules.length; i++) {
        var source = job.profile.modules[i];
        var target = job.geometry.modules[source.role];
        if (source.table && !manifestTableIsRendered(job, source)) {
            tableVerification[source.table.key] = manifestVerifyOmittedTable(doc, job, source);
        }
        if (!target || !target.visible) continue;
        for (var j = 0; j < source.titles.length; j++) {
            var title = source.titles[j];
            if (manifestExcluded(title.path, job.profile.omitted_paths)) continue;
            if (manifestCompactEnabled(job) && manifestCompactPathWasRemoved(job, title.path)) continue;
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
        if (!manifestTableIsRendered(job, source)) continue;
        var parent = findLayer(doc, source.table.parent_path || source.path);
        var table = findLayer(parent, [source.table.key + "（当前数据）"]);
        if (source.role === "size_table") sizeBounds.size_table = box(table);
        var matrix = job.tables[source.table.key];
        manifestCheckRenderedTable(doc, table, matrix, job.geometry.tables[source.table.key], source.table.key);
        tableVerification[source.table.key] = {state: "render", reason: "", emitted: true,
            matrix: matrix, rows: matrix.length - 1, columns: matrix[0].length,
            bounds_px: box(table), region: job.geometry.tables[source.table.key].region,
            editable: true, plan: job.geometry.tables[source.table.key].plan};
    }
    var verification = {
        photo_slots: photoSlots,
        bounds_px: sizeBounds,
        clearance_px: {
            table_measurement: manifestTableSpacing(sizeBounds.size_table, sizeBounds.measurement, "尺码表和量体图", "03选尺码"),
            measurement_note: manifestSpacing(sizeBounds.measurement, sizeBounds.size_note, "量体图和尺码备注"),
            table_note: manifestTableSpacing(sizeBounds.size_table, sizeBounds.size_note, "尺码表和尺码备注", "03选尺码")
        },
        size_note_editable: sizeNoteEditable,
        product_attributes_editable: attributesEditable,
        tables: tableVerification,
        compact_content: manifestVerifyCompactContent(doc, job),
        compact_size_helpers_collapsed: Boolean(sizeTarget && sizeTarget.helper_layout)
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
            verification.clearance_px.table_method = manifestTableSpacing(sizeBounds.size_table, methodBounds, "尺码表和测量方法", "03选尺码");
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
    manifestApplyCompactHelperGeometry(doc, job);
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
    context.stage = "清除未使用的模块和图位";
    manifestPruneCompactOutput(doc, job);
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
