declare var angular: any;

angular.module('supplyForgeApp')
.component('skuDeduplicationTinder', {
    bindings: {
        proposals: '<',
        onMerge: '&',
        onComplete: '&'
    },
    template: `
<style>
    .diff-highlight {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 1px 4px;
        border-radius: 4px;
        border-bottom: 1px solid #F59E0B;
        font-weight: 700;
    }
</style>

<section class="min-h-screen bg-background flex flex-col px-4 md:px-8 py-8">
    <!-- Header with exit and progress -->
    <div class="max-w-5xl mx-auto w-full mb-6 flex items-center justify-between">
        <button ng-click="$ctrl.exitTinder()" class="text-secondary text-sm hover:text-accent transition-colors font-mono font-semibold flex items-center gap-2">
            ← Quay lại Trang chính
        </button>
        <span class="text-xs font-mono text-accent uppercase tracking-widest font-bold flex items-center gap-2">
            <span>🔗</span>
            <span>Rà soát Mã trùng lặp · Công cụ Đối chiếu Kho</span>
        </span>
    </div>

    <!-- Main Reconciliation Container -->
    <div class="max-w-5xl mx-auto w-full flex-1 flex flex-col lg:flex-row gap-8 items-stretch">
        
        <!-- Main Reconciliation Card Area -->
        <div class="flex-1 flex flex-col justify-between">
            <!-- Progress Line -->
            <div class="w-full mb-4">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-xs font-mono text-secondary font-semibold">TIẾN TRÌNH RÀ SOÁT MÃ</span>
                    <span class="text-xs font-mono text-primary font-bold tabular-nums">
                        Cặp {{ $ctrl.index + 1 }} / {{ $ctrl.proposals.length }}
                    </span>
                </div>
                <div class="h-2 bg-gray-200 rounded-full overflow-hidden border border-gray-300/60">
                    <div class="h-full bg-accent transition-all duration-300" ng-style="{ width: $ctrl.progressPct + '%' }"></div>
                </div>
            </div>

            <!-- Reconciliation Worktable Card -->
            <div ng-if="$ctrl.current" class="flex-1 bg-surface border border-border-base shadow-material-lg rounded-3xl overflow-hidden flex flex-col relative">
                
                <!-- Matching header -->
                <div class="flex items-center justify-between px-8 py-4 border-b border-border-base bg-gray-50/80">
                    <div class="flex items-center gap-3">
                        <span class="text-xs font-mono text-secondary uppercase font-semibold">Mức độ tương đồng:</span>
                        <span class="font-mono font-black text-lg text-accent">
                            Giống nhau {{ Math.round($ctrl.current.confidenceScore * 100) }}%
                        </span>
                    </div>
                    <div class="text-right">
                        <span class="text-xs font-mono text-secondary">Phát hiện bởi thuật toán khớp mã đa sàn</span>
                    </div>
                </div>

                <!-- Side-by-Side Attribute Comparison Table -->
                <div class="flex-1 p-6 md:p-8 space-y-6">
                    <div class="grid grid-cols-2 gap-6 pb-4 border-b border-border-base">
                        <!-- Column Left: Sku A -->
                        <div class="space-y-2">
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-mono text-secondary uppercase font-bold">MÃ GỐC (A)</span>
                                <span class="text-[10px] font-mono text-accent bg-blue-50 border border-accent/20 rounded px-2 py-0.5 font-bold">{{ $ctrl.current.skuA.source }}</span>
                            </div>
                            <div class="font-mono text-xs text-secondary">SKU: {{ $ctrl.current.skuA.skuCode }}</div>
                            <div class="text-base leading-relaxed text-primary font-bold pt-1 min-h-[3.5rem]">
                                <span ng-bind-html="$ctrl.getHighlightedA()"></span>
                            </div>
                        </div>

                        <!-- Column Right: Sku B -->
                        <div class="space-y-2 pl-4 border-l border-border-base">
                            <div class="flex items-center gap-2">
                                <span class="text-xs font-mono text-secondary uppercase font-bold">MÃ NGHI NGỜ TRÙNG (B)</span>
                                <span class="text-[10px] font-mono text-warn bg-amber-50 border border-warn/20 rounded px-2 py-0.5 font-bold">{{ $ctrl.current.skuB.source }}</span>
                            </div>
                            <div class="font-mono text-xs text-secondary">SKU: {{ $ctrl.current.skuB.skuCode }}</div>
                            <div class="text-base leading-relaxed text-primary font-bold pt-1 min-h-[3.5rem]">
                                <span ng-bind-html="$ctrl.getHighlightedB()"></span>
                            </div>
                        </div>
                    </div>

                    <!-- Attribute Matrix Comparison Table -->
                    <div>
                        <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-3 font-semibold">Bảng đối chiếu thuộc tính chi tiết</div>
                        <div class="border border-border-base rounded-2xl overflow-hidden shadow-xs text-xs font-mono">
                            <table class="w-full text-left border-collapse">
                                <thead class="bg-gray-100 text-secondary uppercase font-bold border-b border-border-base">
                                    <tr>
                                        <th class="px-4 py-2.5 w-1/3">Thuộc tính đối chiếu</th>
                                        <th class="px-4 py-2.5 w-1/3 text-right">Bên Mã Gốc (A)</th>
                                        <th class="px-4 py-2.5 w-1/3 text-right">Bên Mã Nghi Ngờ (B)</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-border-base">
                                    <tr class="hover:bg-gray-50">
                                        <td class="px-4 py-2.5 text-secondary font-semibold">Giá bán niêm yết</td>
                                        <td class="px-4 py-2.5 text-right font-bold text-primary tabular-nums" ng-class="{'text-danger': $ctrl.current.skuA.price !== $ctrl.current.skuB.price}">
                                            {{ $ctrl.formatVND($ctrl.current.skuA.price) }}
                                        </td>
                                        <td class="px-4 py-2.5 text-right font-bold text-primary tabular-nums" ng-class="{'text-danger': $ctrl.current.skuA.price !== $ctrl.current.skuB.price}">
                                            {{ $ctrl.formatVND($ctrl.current.skuB.price) }}
                                        </td>
                                    </tr>
                                    <tr class="hover:bg-gray-50">
                                        <td class="px-4 py-2.5 text-secondary font-semibold">Số lượng tồn kho thực tế</td>
                                        <td class="px-4 py-2.5 text-right font-bold text-accent tabular-nums">{{ $ctrl.current.skuA.stock }} đơn vị</td>
                                        <td class="px-4 py-2.5 text-right font-bold text-warn tabular-nums">{{ $ctrl.current.skuB.stock }} đơn vị</td>
                                    </tr>
                                    <tr class="hover:bg-gray-50">
                                        <td class="px-4 py-2.5 text-secondary font-semibold">Kênh đồng bộ / Sàn E-com</td>
                                        <td class="px-4 py-2.5 text-right text-primary font-bold">{{ $ctrl.current.skuA.source }}</td>
                                        <td class="px-4 py-2.5 text-right text-primary font-bold">{{ $ctrl.current.skuB.source }}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                <!-- Control decision buttons at Bottom Right -->
                <div class="p-6 border-t border-border-base bg-gray-50/80 flex items-center justify-between">
                    <div class="text-xs text-secondary font-mono">
                        Sử dụng phím tắt bàn phím: <span class="font-bold text-primary">⬅️ (Bỏ qua)</span> hoặc <span class="font-bold text-primary">➡️ (Gộp mã)</span>
                    </div>
                    <div class="flex items-center gap-3">
                        <button ng-click="$ctrl.decide('ignore')" 
                                class="px-6 py-3 rounded-xl border border-border-base text-secondary text-xs font-bold hover:border-danger/40 hover:text-danger transition-all bg-surface shadow-xs hover:bg-red-50 flex items-center gap-2">
                            <span>Bỏ qua (Giữ nguyên 2 mã)</span>
                        </button>
                        <button ng-click="$ctrl.decide('merge')" 
                                class="px-8 py-3 rounded-xl bg-success text-white text-xs font-bold transition-all hover:bg-green-600 shadow-material flex items-center gap-2">
                            <span>Xác nhận Gộp mã</span>
                        </button>
                    </div>
                </div>
            </div>

            <!-- Empty State when no proposals left -->
            <div ng-if="!$ctrl.current" class="flex-1 bg-surface border border-border-base shadow-material rounded-3xl p-12 flex flex-col items-center justify-center text-center">
                <div class="w-16 h-16 rounded-full bg-success/10 text-success text-3xl flex items-center justify-center mb-4">✨</div>
                <h3 class="font-tight font-bold text-primary text-xl mb-2">Hoàn tất rà soát mã trùng lặp!</h3>
                <p class="text-secondary text-sm max-w-md leading-relaxed mb-6">
                    Không còn cặp SKU nghi ngờ trùng lặp nào trong cơ sở dữ liệu. Toàn bộ danh mục tồn kho đã được chuẩn hóa.
                </p>
                <button ng-click="$ctrl.exitTinder()" class="bg-accent text-white font-tight font-bold text-sm px-8 py-3.5 rounded-2xl hover:bg-blue-600 shadow-material transition-all">
                    Quay lại Bảng điều khiển →
                </button>
            </div>
        </div>

        <!-- History Drawer on Side -->
        <div class="w-full lg:w-80 bg-surface border border-border-base rounded-3xl p-6 flex flex-col justify-between shadow-material">
            <div>
                <div class="text-xs font-mono text-secondary uppercase tracking-widest mb-4 pb-2 border-b border-border-base flex justify-between items-center font-bold">
                    <span>Lịch sử đối chiếu</span>
                    <span class="bg-gray-100 px-2 py-0.5 rounded text-[10px] text-primary font-mono">{{ $ctrl.actionHistory.length }} thao tác</span>
                </div>
                
                <div class="space-y-3 overflow-y-auto max-h-[360px] pr-1">
                    <div ng-if="$ctrl.actionHistory.length === 0" class="text-xs text-secondary italic py-8 text-center font-mono">
                        Chưa thực hiện gộp hoặc bỏ qua nào trong phiên này.
                    </div>
                    
                    <div ng-repeat="act in $ctrl.actionHistory | orderBy:'-$index'" 
                         class="p-3.5 rounded-xl border border-border-base bg-gray-50/50 hover:bg-gray-100 transition-colors relative group shadow-xs">
                        <div class="flex justify-between items-start mb-1">
                            <span class="text-[9px] font-mono uppercase tracking-wider px-2 py-0.5 rounded font-bold"
                                  ng-class="{'bg-success/10 text-success border border-success/20': act.type === 'merge', 'bg-danger/10 text-danger border border-danger/20': act.type === 'ignore'}">
                                {{ act.type === 'merge' ? 'Đã gộp' : 'Đã giữ nguyên' }}
                            </span>
                            <button ng-click="$ctrl.undoAction(act)" 
                                    class="text-[10px] font-mono text-warn hover:text-primary bg-amber-50 px-2.5 py-1 rounded transition-all border border-warn/20 font-bold">
                                Hoàn tác
                            </button>
                        </div>
                        <div class="text-xs text-primary font-bold truncate mt-2">{{ act.proposal.skuA.name }}</div>
                        <div class="text-[10px] text-secondary truncate">← {{ act.proposal.skuB.name }}</div>
                    </div>
                </div>
            </div>

            <!-- Side panel footer metrics -->
            <div class="mt-6 pt-4 border-t border-border-base space-y-2">
                <div class="flex justify-between text-xs font-mono text-secondary font-semibold">
                    <span>Đã gộp mã:</span>
                    <span class="text-success font-bold">{{ $ctrl.mergedCount }}</span>
                </div>
                <div class="flex justify-between text-xs font-mono text-secondary font-semibold">
                    <span>Đã bỏ qua:</span>
                    <span class="text-danger font-bold">{{ $ctrl.ignoredCount }}</span>
                </div>
            </div>
        </div>

    </div>
</section>
    `,
    controller: ['$scope', '$document', '$timeout', '$sce', 'apiService', function($scope: any, $document: any, $timeout: any, $sce: any, apiService: any) {
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
        function handleKeyDown(e: KeyboardEvent) {
            if (!ctrl.current) return;
            if (e.key === 'ArrowLeft') {
                $scope.$apply(function() {
                    ctrl.decide('ignore');
                });
            } else if (e.key === 'ArrowRight') {
                $scope.$apply(function() {
                    ctrl.decide('merge');
                });
            }
        }

        ctrl.$onInit = function() {
            ctrl.resetState();
            $document.on('keydown', handleKeyDown);
        };

        ctrl.$onDestroy = function() {
            $document.off('keydown', handleKeyDown);
        };

        ctrl.resetState = function() {
            if (ctrl.proposals && ctrl.proposals.length > 0) {
                ctrl.current = ctrl.proposals[ctrl.index];
                ctrl.updateProgress();
            } else {
                ctrl.current = null;
                ctrl.progressPct = 0;
            }
        };

        ctrl.updateProgress = function() {
            if (!ctrl.proposals || ctrl.proposals.length === 0) {
                ctrl.progressPct = 0;
            } else {
                ctrl.progressPct = (ctrl.index / ctrl.proposals.length) * 100;
            }
        };

        ctrl.decide = function(decision: 'merge' | 'ignore') {
            if (!ctrl.current) return;

            var currentProposal = ctrl.current;
            ctrl.actionOverlay = decision;

            // Wait for micro-animation overlay before advancing
            $timeout(function() {
                ctrl.actionOverlay = null;

                if (decision === 'merge') {
                    // Trigger merge in backend
                    ctrl.onMerge({ a: currentProposal.skuA, b: currentProposal.skuB });
                    ctrl.mergedCount++;
                    ctrl.actionHistory.push({
                        type: 'merge',
                        proposal: currentProposal
                    });
                } else {
                    // Trigger ignore in backend (Human-in-the-loop learn)
                    apiService.ignorePair(ctrl.workspaceId, currentProposal.skuA.id, currentProposal.skuB.id, ctrl.userId)
                        .catch(function(err: any) {
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
                } else {
                    ctrl.current = ctrl.proposals[ctrl.index];
                    ctrl.updateProgress();
                }
            }, 400);
        };

        // Undo Merge / Revert Ignore function
        ctrl.undoAction = function(action: any) {
            var actionIdx = ctrl.actionHistory.indexOf(action);
            if (actionIdx === -1) return;

            if (action.type === 'merge') {
                // Call undo merge on backend
                apiService.undoMerge(ctrl.workspaceId, action.proposal.skuA.id, action.proposal.skuB.id)
                    .then(function() {
                        console.log("Successfully undid merge on backend:", action.proposal.skuA.name, "<-", action.proposal.skuB.name);
                    })
                    .catch(function(err: any) {
                        alert("Không thể hoàn tác gộp trên CSDL: " + (err.data && err.data.error ? err.data.error : err.statusText));
                    });
                ctrl.mergedCount = Math.max(0, ctrl.mergedCount - 1);
            } else {
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

        ctrl.exitTinder = function() {
            ctrl.onComplete({ merged: ctrl.mergedCount, ignored: ctrl.ignoredCount });
        };

        // Difference Highlighting Engine
        ctrl.highlightDiff = function(strA: string, strB: string) {
            if (!strA) return '';
            if (!strB) return ctrl.escapeHtml(strA);

            var wordsA = strA.split(/\s+/);
            var wordsB = strB.split(/\s+/);
            var normalizedB = wordsB.map(function(w) { return w.toLowerCase(); });

            var html = [];
            for (var i = 0; i < wordsA.length; i++) {
                var word = wordsA[i];
                var nWord = word.toLowerCase();

                if (normalizedB.indexOf(nWord) === -1) {
                    html.push('<span class="diff-highlight">' + ctrl.escapeHtml(word) + '</span>');
                } else {
                    html.push(ctrl.escapeHtml(word));
                }
            }
            return html.join(' ');
        };

        ctrl.escapeHtml = function(text: string) {
            if (!text) return '';
            return text.toString()
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;")
                .replace(/"/g, "&quot;")
                .replace(/'/g, "&#039;");
        };

        ctrl.getHighlightedA = function() {
            if (!ctrl.current) return '';
            return $sce.trustAsHtml(ctrl.highlightDiff(ctrl.current.skuA.name, ctrl.current.skuB.name));
        };

        ctrl.getHighlightedB = function() {
            if (!ctrl.current) return '';
            return $sce.trustAsHtml(ctrl.highlightDiff(ctrl.current.skuB.name, ctrl.current.skuA.name));
        };

        ctrl.formatVND = function(value: number) {
            if (!value) return "0 ₫";
            return Math.round(value).toLocaleString('vi-VN') + ' ₫';
        };
    }]
});
