console.log("data-mapping-confirm.component.js HAS BEEN LOADED AND EXECUTED BY BROWSER!");
angular.module('supplyForgeApp')
    .component('dataMappingConfirm', {
    bindings: {
        headers: '<',
        sampleData: '<',
        aiSuggestions: '<',
        onConfirm: '&'
    },
    template: "\n<div class=\"min-h-screen bg-background flex flex-col justify-center px-6 md:px-16 lg:px-24 py-16\">\n    <div class=\"max-w-3xl mx-auto w-full\">\n        <!-- Header -->\n        <div class=\"mb-12\">\n            <p class=\"text-xs font-mono text-accent tracking-widest uppercase mb-4 opacity-85\">\n                B\u01B0\u1EDBc 3: AI Column Mapping\n            </p>\n            <h2 class=\"font-tight font-black text-primary text-4xl sm:text-5xl tracking-tightest leading-tight\">\n                X\u00E1c nh\u1EADn \u00E1nh x\u1EA1 tr\u01B0\u1EDDng d\u1EEF li\u1EC7u.\n            </h2>\n            <p class=\"text-secondary text-sm mt-3 max-w-xl\">\n                AI \u0111\u00E3 \u0111\u1EC1 xu\u1EA5t \u00E1nh x\u1EA1 c\u00E1c c\u1ED9t t\u1EEB file c\u1EE7a b\u1EA1n. Vui l\u00F2ng ki\u1EC3m tra l\u1EA1i s\u1EF1 chu\u1EA9n x\u00E1c b\u00EAn d\u01B0\u1EDBi \u0111\u1EC3 b\u1EAFt \u0111\u1EA7u n\u1EA1p c\u01A1 s\u1EDF d\u1EEF li\u1EC7u.\n            </p>\n        </div>\n\n        <!-- Form mapping card -->\n        <div class=\"bg-surface border border-border-base rounded-2xl p-6 sm:p-8 space-y-6\">\n            <div class=\"text-xs font-mono text-secondary/30 uppercase tracking-widest pb-4 border-b border-[#1c1c1c]\">\n                \u00C1nh x\u1EA1 tr\u01B0\u1EDDng c\u01A1 s\u1EDF d\u1EEF li\u1EC7u (Database Mapping)\n            </div>\n\n            <div class=\"space-y-4\">\n                <!-- Field rows loop -->\n                <div ng-repeat=\"field in $ctrl.fields\" class=\"flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl border border-border-base bg-[#0e0e0e] hover:bg-[#121212] transition-colors\">\n                    <div>\n                        <div class=\"text-sm font-bold text-primary\">{{ field.label }}</div>\n                        <div class=\"text-xs text-secondary/60 mt-0.5\">{{ field.desc }}</div>\n                    </div>\n                    <div class=\"flex items-center gap-4\">\n                        <!-- Sample preview value from CSV -->\n                        <span ng-if=\"$ctrl.sampleData\" class=\"text-xs font-mono text-secondary/40 max-w-[150px] truncate\" title=\"M\u1EABu: {{ $ctrl.getSampleValue(field.key) }}\">\n                            M\u1EABu: {{ $ctrl.getSampleValue(field.key) || '\u2014' }}\n                        </span>\n                        <!-- Column selector select box -->\n                        <select ng-model=\"$ctrl.finalMapping[field.key]\" \n                                ng-change=\"$ctrl.updateMapping(field.key)\"\n                                class=\"bg-surface border border-border-base rounded px-3 py-2 text-xs text-primary font-mono outline-none focus:border-accent\">\n                            <option value=\"\">-- B\u1ECF qua c\u1ED9t --</option>\n                            <option ng-repeat=\"h in $ctrl.headers\" value=\"{{ h }}\">{{ h }}</option>\n                        </select>\n                    </div>\n                </div>\n            </div>\n\n            <!-- Confirm button -->\n            <div class=\"pt-6 border-t border-[#1c1c1c] flex items-center justify-between\">\n                <span class=\"text-xs font-mono text-accent\">\n                    AI Confidence: {{ $ctrl.aiSuggestions.confidence || 'Medium' }}\n                </span>\n                <button ng-click=\"$ctrl.confirm()\" class=\"bg-accent text-background font-tight font-black text-xs px-8 py-3.5 rounded-xl hover:bg-[#deff5a] active:scale-[0.98] transition-all\">\n                    \u0110\u1ED3ng \u00FD & N\u1EA1p d\u1EEF li\u1EC7u \u2192\n                </button>\n            </div>\n        </div>\n    </div>\n</div>\n    ",
    controller: [function () {
            console.log("dataMappingConfirm component controller instantiated!");
            var ctrl = this;
            // DB Core columns to map
            ctrl.fields = [
                { key: 'productName', label: 'Tên sản phẩm', desc: 'Tên hoặc nhãn hiệu của SKU' },
                { key: 'itemSku', label: 'Mã SKU', desc: 'Mã vạch hoặc mã ký tự SKU định danh' },
                { key: 'price', label: 'Giá bán', desc: 'Giá niêm yết bán lẻ cho người tiêu dùng' },
                { key: 'cost', label: 'Giá vốn', desc: 'Giá nhập kho của lô hàng' },
                { key: 'stock', label: 'Tồn kho', desc: 'Số lượng đơn vị còn tồn kho' },
                { key: 'orderDate', label: 'Ngày ghi nhận', desc: 'Ngày nhập kho hoặc ngày giao dịch gần nhất' }
            ];
            ctrl.finalMapping = {};
            ctrl.$onInit = function () {
                console.log("dataMappingConfirm $onInit called with bindings:", {
                    headers: ctrl.headers,
                    sampleData: ctrl.sampleData,
                    aiSuggestions: ctrl.aiSuggestions
                });
                // Apply suggestions from AI response
                if (ctrl.aiSuggestions && ctrl.headers) {
                    var mappingKeys = {
                        productName: 'product_name',
                        itemSku: 'item_sku',
                        price: 'price',
                        cost: 'cost',
                        stock: 'stock',
                        orderDate: 'date'
                    };
                    angular.forEach(mappingKeys, function (sugKey, dbKey) {
                        var columnName = ctrl.aiSuggestions[sugKey];
                        if (columnName && ctrl.headers.indexOf(columnName) !== -1) {
                            ctrl.finalMapping[dbKey] = columnName;
                        }
                    });
                    // Fallbacks if mapping is not fully populated
                    if (!ctrl.finalMapping['productName'] && ctrl.headers.length > 0) {
                        ctrl.finalMapping['productName'] = ctrl.headers[0];
                    }
                    if (!ctrl.finalMapping['itemSku'] && ctrl.headers.length > 0) {
                        ctrl.finalMapping['itemSku'] = ctrl.headers[0];
                    }
                }
            };
            ctrl.getSampleValue = function (fieldKey) {
                if (!ctrl.sampleData || !ctrl.headers)
                    return null;
                var header = ctrl.finalMapping[fieldKey];
                if (!header)
                    return null;
                var idx = ctrl.headers.indexOf(header);
                return idx >= 0 && idx < ctrl.sampleData.length ? ctrl.sampleData[idx] : null;
            };
            ctrl.updateMapping = function (fieldKey) {
                // Trigger recalculation if selector changes
            };
            ctrl.confirm = function () {
                ctrl.onConfirm({ finalMapping: ctrl.finalMapping });
            };
        }]
});
//# sourceMappingURL=data-mapping-confirm.component.js.map