function templateStructureSummary(doc) {
    var budget = {remaining: 240};
    function children(parent, depth, rootLevel) {
        var result = [];
        var layers = parent.layers;
        var count = layers.length;
        var limit = rootLevel ? 100 : 24;
        for (var i = 0; i < count && i < limit && (rootLevel || budget.remaining > 0); i++) {
            var layer = layers[i];
            if (!rootLevel) budget.remaining--;
            var item = {name: String(layer.name).substring(0, 200), type: layer.typename, visible: layer.visible};
            if (depth > 0 && layer.typename === "LayerSet") item.children = children(layer, depth - 1, false);
            result.push(item);
        }
        if (count > result.length) result.push({omitted_children: count - result.length});
        return result;
    }
    return children(doc, 2, true);
}

function classifyTemplateDocument(doc, spec) {
    var matches = [];
    var attempts = [];
    function probe(family, label, inspect) {
        var attempt = {family: family, label: label, matched: false, missing: []};
        try {
            var bindings = inspect();
            if (bindings) {
                attempt.matched = true;
                matches.push({family: family, bindings: bindings});
            } else attempt.missing.push("未找到此类母版的商品信息入口");
        } catch (error) {
            attempt.missing.push(String(error.message));
        }
        attempts.push(attempt);
    }
    probe("classic", "产品信息／产品信息T", function () {
        var product = optionalClassicLayer(doc, "产品信息 拷贝 2");
        return product && product.visible ? classicTemplateProfile(doc) : null;
    });
    probe("section", "独立分组母版", function () { return sectionTemplateProfile(doc); });
    probe("workbench", "已整理裤装工作母版", function () {
        checkWorkbenchTemplate(doc);
        return {family: "workbench"};
    });
    probe("raw_workbench", "原始裤装长版", function () { return validateRawWorkbenchTemplate(doc); });
    if (matches.length === 1) return matches[0];
    var reason = matches.length ? "存在多个匹配的版式，需先明确实际模块" : "尚未匹配到已支持的版式";
    var message = "当前母版" + reason + "。";
    for (var i = 0; i < attempts.length; i++) {
        if (attempts[i].missing.length) message += "\n" + attempts[i].label + "：" + attempts[i].missing.join("；");
    }
    var details = {
        version: 1, status: "unsupported", message: message,
        source: spec.originalSource || spec.source,
        canvas: {width: doc.width.as("px"), height: doc.height.as("px")},
        families: attempts, roots: templateStructureSummary(doc)
    };
    if (spec.diagnosticsOutput) {
        try {
            manifestWrite(spec.diagnosticsOutput, details);
            message += "\n已保存分组检查结果：" + spec.diagnosticsOutput;
        } catch (writeError) {
            message += "\n分组检查结果未能保存：" + writeError.message;
        }
    }
    throw new Error("[UNSUPPORTED_TEMPLATE] " + message);
}
