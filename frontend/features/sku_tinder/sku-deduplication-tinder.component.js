angular.module('supplyForgeApp')
    .component('skuDeduplicationTinder', {
    bindings: {
        proposals: '<',
        onMerge: '&',
        onComplete: '&'
    },
    template: "\n<style>\n    .diff-highlight {\n        background-color: #FEF3C7;\n        color: #92400E;\n        padding: 1px 4px;\n        border-radius: 4px;\n        border-bottom: 1px solid #F59E0B;\n        font-weight: 700;\n    }\n</style>\n\n<section class=\"min-h-screen bg-background flex flex-col px-4 md:px-8 py-8\">\n    <!-- Header with exit and progress -->\n    <div class=\"max-w-5xl mx-auto w-full mb-6 flex items-center justify-between\">\n        <button ng-click=\"$ctrl.exitTinder()\" class=\"text-secondary text-sm hover:text-accent transition-colors font-mono font-semibold flex items-center gap-2\">\n            \u2190 Quay l\u1EA1i Trang ch\u00EDnh\n        </button>\n        <span class=\"text-xs font-mono text-accent uppercase tracking-widest font-bold flex items-center gap-2\">\n            <span>\uD83D\uDD17</span>\n            <span>R\u00E0 so\u00E1t M\u00E3 tr\u00F9ng l\u1EB7p \u00B7 C\u00F4ng c\u1EE5 \u0110\u1ED1i chi\u1EBFu Kho</span>\n        </span>\n    </div>\n\n    <!-- Main Reconciliation Container -->\n    <div class=\"max-w-5xl mx-auto w-full flex-1 flex flex-col lg:flex-row gap-8 items-stretch\">\n        \n        <!-- Main Reconciliation Card Area -->\n        <div class=\"flex-1 flex flex-col justify-between\">\n            <!-- Progress Line -->\n            <div class=\"w-full mb-4\">\n                <div class=\"flex items-center justify-between mb-2\">\n                    <span class=\"text-xs font-mono text-secondary font-semibold\">TI\u1EBEN TR\u00CCNH R\u00C0 SO\u00C1T M\u00C3</span>\n                    <span class=\"text-xs font-mono text-primary font-bold tabular-nums\">\n                        C\u1EB7p {{ $ctrl.index + 1 }} / {{ $ctrl.proposals.length }}\n                    </span>\n                </div>\n                <div class=\"h-2 bg-gray-200 rounded-full overflow-hidden border border-gray-300/60\">\n                    <div class=\"h-full bg-accent transition-all duration-300\" ng-style=\"{ width: $ctrl.progressPct + '%' }\"></div>\n                </div>\n            </div>\n\n            <!-- Reconciliation Worktable Card -->\n            <div ng-if=\"$ctrl.current\" class=\"flex-1 bg-surface border border-border-base shadow-material-lg rounded-3xl overflow-hidden flex flex-col relative\">\n                \n                <!-- Matching header -->\n                <div class=\"flex items-center justify-between px-8 py-4 border-b border-border-base bg-gray-50/80\">\n                    <div class=\"flex items-center gap-3\">\n                        <span class=\"text-xs font-mono text-secondary uppercase font-semibold\">M\u1EE9c \u0111\u1ED9 t\u01B0\u01A1ng \u0111\u1ED3ng:</span>\n                        <span class=\"font-mono font-black text-lg text-accent\">\n                            Gi\u1ED1ng nhau {{ Math.round($ctrl.current.confidenceScore * 100) }}%\n                        </span>\n                    </div>\n                    <div class=\"text-right\">\n                        <span class=\"text-xs font-mono text-secondary\">Ph\u00E1t hi\u1EC7n b\u1EDFi thu\u1EADt to\u00E1n kh\u1EDBp m\u00E3 \u0111a s\u00E0n</span>\n                    </div>\n                </div>\n\n                <!-- Side-by-Side Attribute Comparison Table -->\n                <div class=\"flex-1 p-6 md:p-8 space-y-6\">\n                    <div class=\"grid grid-cols-2 gap-6 pb-4 border-b border-border-base\">\n                        <!-- Column Left: Sku A -->\n                        <div class=\"space-y-2\">\n                            <div class=\"flex items-center gap-2\">\n                                <span class=\"text-xs font-mono text-secondary uppercase font-bold\">M\u00C3 G\u1ED0C (A)</span>\n                                <span class=\"text-[10px] font-mono text-accent bg-blue-50 border border-accent/20 rounded px-2 py-0.5 font-bold\">{{ $ctrl.current.skuA.source }}</span>\n                            </div>\n                            <div class=\"font-mono text-xs text-secondary\">SKU: {{ $ctrl.current.skuA.skuCode }}</div>\n                            <div class=\"text-base leading-relaxed text-primary font-bold pt-1 min-h-[3.5rem]\">\n                                <span ng-bind-html=\"$ctrl.getHighlightedA()\"></span>\n                            </div>\n                        </div>\n\n                        <!-- Column Right: Sku B -->\n                        <div class=\"space-y-2 pl-4 border-l border-border-base\">\n                            <div class=\"flex items-center gap-2\">\n                                <span class=\"text-xs font-mono text-secondary uppercase font-bold\">M\u00C3 NGHI NG\u1EDC TR\u00D9NG (B)</span>\n                                <span class=\"text-[10px] font-mono text-warn bg-amber-50 border border-warn/20 rounded px-2 py-0.5 font-bold\">{{ $ctrl.current.skuB.source }}</span>\n                            </div>\n                            <div class=\"font-mono text-xs text-secondary\">SKU: {{ $ctrl.current.skuB.skuCode }}</div>\n                            <div class=\"text-base leading-relaxed text-primary font-bold pt-1 min-h-[3.5rem]\">\n                                <span ng-bind-html=\"$ctrl.getHighlightedB()\"></span>\n                            </div>\n                        </div>\n                    </div>\n\n                    <!-- Attribute Matrix Comparison Table -->\n                    <div>\n                        <div class=\"text-xs font-mono text-secondary uppercase tracking-widest mb-3 font-semibold\">B\u1EA3ng \u0111\u1ED1i chi\u1EBFu thu\u1ED9c t\u00EDnh chi ti\u1EBFt</div>\n                        <div class=\"border border-border-base rounded-2xl overflow-hidden shadow-xs text-xs font-mono\">\n                            <table class=\"w-full text-left border-collapse\">\n                                <thead class=\"bg-gray-100 text-secondary uppercase font-bold border-b border-border-base\">\n                                    <tr>\n                                        <th class=\"px-4 py-2.5 w-1/3\">Thu\u1ED9c t\u00EDnh \u0111\u1ED1i chi\u1EBFu</th>\n                                        <th class=\"px-4 py-2.5 w-1/3 text-right\">B\u00EAn M\u00E3 G\u1ED1c (A)</th>\n                                        <th class=\"px-4 py-2.5 w-1/3 text-right\">B\u00EAn M\u00E3 Nghi Ng\u1EDD (B)</th>\n                                    </tr>\n                                </thead>\n                                <tbody class=\"divide-y divide-border-base\">\n                                    <tr class=\"hover:bg-gray-50\">\n                                        <td class=\"px-4 py-2.5 text-secondary font-semibold\">Gi\u00E1 b\u00E1n ni\u00EAm y\u1EBFt</td>\n                                        <td class=\"px-4 py-2.5 text-right font-bold text-primary tabular-nums\" ng-class=\"{'text-danger': $ctrl.current.skuA.price !== $ctrl.current.skuB.price}\">\n                                            {{ $ctrl.formatVND($ctrl.current.skuA.price) }}\n                                        </td>\n                                        <td class=\"px-4 py-2.5 text-right font-bold text-primary tabular-nums\" ng-class=\"{'text-danger': $ctrl.current.skuA.price !== $ctrl.current.skuB.price}\">\n                                            {{ $ctrl.formatVND($ctrl.current.skuB.price) }}\n                                        </td>\n                                    </tr>\n                                    <tr class=\"hover:bg-gray-50\">\n                                        <td class=\"px-4 py-2.5 text-secondary font-semibold\">S\u1ED1 l\u01B0\u1EE3ng t\u1ED3n kho th\u1EF1c t\u1EBF</td>\n                                        <td class=\"px-4 py-2.5 text-right font-bold text-accent tabular-nums\">{{ $ctrl.current.skuA.stock }} \u0111\u01A1n v\u1ECB</td>\n                                        <td class=\"px-4 py-2.5 text-right font-bold text-warn tabular-nums\">{{ $ctrl.current.skuB.stock }} \u0111\u01A1n v\u1ECB</td>\n                                    </tr>\n                                    <tr class=\"hover:bg-gray-50\">\n                                        <td class=\"px-4 py-2.5 text-secondary font-semibold\">K\u00EAnh \u0111\u1ED3ng b\u1ED9 / S\u00E0n E-com</td>\n                                        <td class=\"px-4 py-2.5 text-right text-primary font-bold\">{{ $ctrl.current.skuA.source }}</td>\n                                        <td class=\"px-4 py-2.5 text-right text-primary font-bold\">{{ $ctrl.current.skuB.source }}</td>\n                                    </tr>\n                                </tbody>\n                            </table>\n                        </div>\n                    </div>\n                </div>\n\n                <!-- Control decision buttons at Bottom Right -->\n                <div class=\"p-6 border-t border-border-base bg-gray-50/80 flex items-center justify-between\">\n                    <div class=\"text-xs text-secondary font-mono\">\n                        S\u1EED d\u1EE5ng ph\u00EDm t\u1EAFt b\u00E0n ph\u00EDm: <span class=\"font-bold text-primary\">\u2B05\uFE0F (B\u1ECF qua)</span> ho\u1EB7c <span class=\"font-bold text-primary\">\u27A1\uFE0F (G\u1ED9p m\u00E3)</span>\n                    </div>\n                    <div class=\"flex items-center gap-3\">\n                        <button ng-click=\"$ctrl.decide('ignore')\" \n                                class=\"px-6 py-3 rounded-xl border border-border-base text-secondary text-xs font-bold hover:border-danger/40 hover:text-danger transition-all bg-surface shadow-xs hover:bg-red-50 flex items-center gap-2\">\n                            <span>B\u1ECF qua (Gi\u1EEF nguy\u00EAn 2 m\u00E3)</span>\n                        </button>\n                        <button ng-click=\"$ctrl.decide('merge')\" \n                                class=\"px-8 py-3 rounded-xl bg-success text-white text-xs font-bold transition-all hover:bg-green-600 shadow-material flex items-center gap-2\">\n                            <span>X\u00E1c nh\u1EADn G\u1ED9p m\u00E3</span>\n                        </button>\n                    </div>\n                </div>\n            </div>\n\n            <!-- Empty State when no proposals left -->\n            <div ng-if=\"!$ctrl.current\" class=\"flex-1 bg-surface border border-border-base shadow-material rounded-3xl p-12 flex flex-col items-center justify-center text-center\">\n                <div class=\"w-16 h-16 rounded-full bg-success/10 text-success text-3xl flex items-center justify-center mb-4\">\u2728</div>\n                <h3 class=\"font-tight font-bold text-primary text-xl mb-2\">Ho\u00E0n t\u1EA5t r\u00E0 so\u00E1t m\u00E3 tr\u00F9ng l\u1EB7p!</h3>\n                <p class=\"text-secondary text-sm max-w-md leading-relaxed mb-6\">\n                    Kh\u00F4ng c\u00F2n c\u1EB7p SKU nghi ng\u1EDD tr\u00F9ng l\u1EB7p n\u00E0o trong c\u01A1 s\u1EDF d\u1EEF li\u1EC7u. To\u00E0n b\u1ED9 danh m\u1EE5c t\u1ED3n kho \u0111\u00E3 \u0111\u01B0\u1EE3c chu\u1EA9n h\u00F3a.\n                </p>\n                <button ng-click=\"$ctrl.exitTinder()\" class=\"bg-accent text-white font-tight font-bold text-sm px-8 py-3.5 rounded-2xl hover:bg-blue-600 shadow-material transition-all\">\n                    Quay l\u1EA1i B\u1EA3ng \u0111i\u1EC1u khi\u1EC3n \u2192\n                </button>\n            </div>\n        </div>\n\n        <!-- History Drawer on Side -->\n        <div class=\"w-full lg:w-80 bg-surface border border-border-base rounded-3xl p-6 flex flex-col justify-between shadow-material\">\n            <div>\n                <div class=\"text-xs font-mono text-secondary uppercase tracking-widest mb-4 pb-2 border-b border-border-base flex justify-between items-center font-bold\">\n                    <span>L\u1ECBch s\u1EED \u0111\u1ED1i chi\u1EBFu</span>\n                    <span class=\"bg-gray-100 px-2 py-0.5 rounded text-[10px] text-primary font-mono\">{{ $ctrl.actionHistory.length }} thao t\u00E1c</span>\n                </div>\n                \n                <div class=\"space-y-3 overflow-y-auto max-h-[360px] pr-1\">\n                    <div ng-if=\"$ctrl.actionHistory.length === 0\" class=\"text-xs text-secondary italic py-8 text-center font-mono\">\n                        Ch\u01B0a th\u1EF1c hi\u1EC7n g\u1ED9p ho\u1EB7c b\u1ECF qua n\u00E0o trong phi\u00EAn n\u00E0y.\n                    </div>\n                    \n                    <div ng-repeat=\"act in $ctrl.actionHistory | orderBy:'-$index'\" \n                         class=\"p-3.5 rounded-xl border border-border-base bg-gray-50/50 hover:bg-gray-100 transition-colors relative group shadow-xs\">\n                        <div class=\"flex justify-between items-start mb-1\">\n                            <span class=\"text-[9px] font-mono uppercase tracking-wider px-2 py-0.5 rounded font-bold\"\n                                  ng-class=\"{'bg-success/10 text-success border border-success/20': act.type === 'merge', 'bg-danger/10 text-danger border border-danger/20': act.type === 'ignore'}\">\n                                {{ act.type === 'merge' ? '\u0110\u00E3 g\u1ED9p' : '\u0110\u00E3 gi\u1EEF nguy\u00EAn' }}\n                            </span>\n                            <button ng-click=\"$ctrl.undoAction(act)\" \n                                    class=\"text-[10px] font-mono text-warn hover:text-primary bg-amber-50 px-2.5 py-1 rounded transition-all border border-warn/20 font-bold\">\n                                Ho\u00E0n t\u00E1c\n                            </button>\n                        </div>\n                        <div class=\"text-xs text-primary font-bold truncate mt-2\">{{ act.proposal.skuA.name }}</div>\n                        <div class=\"text-[10px] text-secondary truncate\">\u2190 {{ act.proposal.skuB.name }}</div>\n                    </div>\n                </div>\n            </div>\n\n            <!-- Side panel footer metrics -->\n            <div class=\"mt-6 pt-4 border-t border-border-base space-y-2\">\n                <div class=\"flex justify-between text-xs font-mono text-secondary font-semibold\">\n                    <span>\u0110\u00E3 g\u1ED9p m\u00E3:</span>\n                    <span class=\"text-success font-bold\">{{ $ctrl.mergedCount }}</span>\n                </div>\n                <div class=\"flex justify-between text-xs font-mono text-secondary font-semibold\">\n                    <span>\u0110\u00E3 b\u1ECF qua:</span>\n                    <span class=\"text-danger font-bold\">{{ $ctrl.ignoredCount }}</span>\n                </div>\n            </div>\n        </div>\n\n    </div>\n</section>\n    ",
    controller: ['$scope', '$document', '$timeout', '$sce', 'apiService', function ($scope, $document, $timeout, $sce, apiService) {
            var ctrl = this;
            ctrl.index = 0;
            ctrl.mergedCount = 0;
            ctrl.ignoredCount = 0;
            ctrl.progressPct = 0;
            ctrl.current = null;
            ctrl.actionOverlay = null; // 'merge' | 'ignore' | null
            ctrl.actionHistory = []; // list of { type: 'merge'|'ignore', proposal: any }
            // Workspace configurables (default to 1 / default user)
            ctrl.workspaceId = 1;
            ctrl.userId = 'user_default_001';
            // Keyboard navigation handler
            function handleKeyDown(e) {
                if (!ctrl.current)
                    return;
                if (e.key === 'ArrowLeft') {
                    $scope.$apply(function () {
                        ctrl.decide('ignore');
                    });
                }
                else if (e.key === 'ArrowRight') {
                    $scope.$apply(function () {
                        ctrl.decide('merge');
                    });
                }
            }
            ctrl.$onInit = function () {
                ctrl.resetState();
                $document.on('keydown', handleKeyDown);
            };
            ctrl.$onDestroy = function () {
                $document.off('keydown', handleKeyDown);
            };
            ctrl.resetState = function () {
                if (ctrl.proposals && ctrl.proposals.length > 0) {
                    ctrl.current = ctrl.proposals[ctrl.index];
                    ctrl.updateProgress();
                }
                else {
                    ctrl.current = null;
                    ctrl.progressPct = 0;
                }
            };
            ctrl.updateProgress = function () {
                if (!ctrl.proposals || ctrl.proposals.length === 0) {
                    ctrl.progressPct = 0;
                }
                else {
                    ctrl.progressPct = (ctrl.index / ctrl.proposals.length) * 100;
                }
            };
            ctrl.decide = function (decision) {
                if (!ctrl.current)
                    return;
                var currentProposal = ctrl.current;
                ctrl.actionOverlay = decision;
                // Wait for micro-animation overlay before advancing
                $timeout(function () {
                    ctrl.actionOverlay = null;
                    if (decision === 'merge') {
                        // Trigger merge in backend
                        ctrl.onMerge({ a: currentProposal.skuA, b: currentProposal.skuB });
                        ctrl.mergedCount++;
                        ctrl.actionHistory.push({
                            type: 'merge',
                            proposal: currentProposal
                        });
                    }
                    else {
                        // Trigger ignore in backend (Human-in-the-loop learn)
                        apiService.ignorePair(ctrl.workspaceId, currentProposal.skuA.id, currentProposal.skuB.id, ctrl.userId)
                            .catch(function (err) {
                            console.error("Failed to register ignored pair in DB:", err);
                        });
                        ctrl.ignoredCount++;
                        ctrl.actionHistory.push({
                            type: 'ignore',
                            proposal: currentProposal
                        });
                    }
                    ctrl.index++;
                    if (ctrl.index >= ctrl.proposals.length) {
                        // Finished all recommendations
                        ctrl.onComplete({ merged: ctrl.mergedCount, ignored: ctrl.ignoredCount });
                    }
                    else {
                        ctrl.current = ctrl.proposals[ctrl.index];
                        ctrl.updateProgress();
                    }
                }, 400);
            };
            // Undo Merge / Revert Ignore function
            ctrl.undoAction = function (action) {
                var actionIdx = ctrl.actionHistory.indexOf(action);
                if (actionIdx === -1)
                    return;
                if (action.type === 'merge') {
                    // Call undo merge on backend
                    apiService.undoMerge(ctrl.workspaceId, action.proposal.skuA.id, action.proposal.skuB.id)
                        .then(function () {
                        console.log("Successfully undid merge on backend:", action.proposal.skuA.name, "<-", action.proposal.skuB.name);
                    })
                        .catch(function (err) {
                        alert("Không thể hoàn tác gộp trên CSDL: " + (err.data && err.data.error ? err.data.error : err.statusText));
                    });
                    ctrl.mergedCount = Math.max(0, ctrl.mergedCount - 1);
                }
                else {
                    // Ignore rollback: simply decrement counter
                    ctrl.ignoredCount = Math.max(0, ctrl.ignoredCount - 1);
                }
                // Remove from history
                ctrl.actionHistory.splice(actionIdx, 1);
                // Re-insert proposal at the current index, so it becomes the active card
                ctrl.proposals.splice(ctrl.index, 0, action.proposal);
                // Re-establish active proposal view
                ctrl.current = ctrl.proposals[ctrl.index];
                ctrl.updateProgress();
            };
            ctrl.exitTinder = function () {
                ctrl.onComplete({ merged: ctrl.mergedCount, ignored: ctrl.ignoredCount });
            };
            // Difference Highlighting Engine
            ctrl.highlightDiff = function (strA, strB) {
                if (!strA)
                    return '';
                if (!strB)
                    return ctrl.escapeHtml(strA);
                var wordsA = strA.split(/\s+/);
                var wordsB = strB.split(/\s+/);
                var normalizedB = wordsB.map(function (w) { return w.toLowerCase(); });
                var html = [];
                for (var i = 0; i < wordsA.length; i++) {
                    var word = wordsA[i];
                    var nWord = word.toLowerCase();
                    if (normalizedB.indexOf(nWord) === -1) {
                        html.push('<span class="diff-highlight">' + ctrl.escapeHtml(word) + '</span>');
                    }
                    else {
                        html.push(ctrl.escapeHtml(word));
                    }
                }
                return html.join(' ');
            };
            ctrl.escapeHtml = function (text) {
                if (!text)
                    return '';
                return text.toString()
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");
            };
            ctrl.getHighlightedA = function () {
                if (!ctrl.current)
                    return '';
                return $sce.trustAsHtml(ctrl.highlightDiff(ctrl.current.skuA.name, ctrl.current.skuB.name));
            };
            ctrl.getHighlightedB = function () {
                if (!ctrl.current)
                    return '';
                return $sce.trustAsHtml(ctrl.highlightDiff(ctrl.current.skuB.name, ctrl.current.skuA.name));
            };
            ctrl.formatVND = function (value) {
                if (!value)
                    return "0 ₫";
                return Math.round(value).toLocaleString('vi-VN') + ' ₫';
            };
        }]
});
//# sourceMappingURL=sku-deduplication-tinder.component.js.map