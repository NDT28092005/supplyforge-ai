import { Component, Input, Output, EventEmitter, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatchProposal } from '../match-proposal';
import { ActionHistory } from '../action-history';

@Component({
  selector: 'app-sku-deduplication-tinder',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './sku-deduplication-tinder.component.html',
  styleUrls: ['./sku-deduplication-tinder.component.css']
})
export class SkuDeduplicationTinderComponent implements OnInit, OnDestroy {
  @Input() proposals: MatchProposal[] = [];
  @Output() merge = new EventEmitter<{ a: any, b: any }>();
  @Output() complete = new EventEmitter<{ merged: number, ignored: number }>();

  index = 0;
  mergedCount = 0;
  ignoredCount = 0;
  progressPct = 0;
  current: MatchProposal | null = null;
  actionHistory: ActionHistory[] = [];

  Math = Math;

  @HostListener('window:keydown', ['$event'])
  handleKeyDown(event: KeyboardEvent): void {
    if (!this.current) return;
    if (event.key === 'ArrowLeft') {
      this.decide('ignore');
    } else if (event.key === 'ArrowRight') {
      this.decide('merge');
    }
  }

  ngOnInit(): void {
    this.resetState();
  }

  ngOnDestroy(): void {}

  resetState(): void {
    if (this.proposals && this.proposals.length > 0) {
      this.current = this.proposals[this.index];
      this.updateProgress();
    } else {
      this.current = null;
      this.progressPct = 0;
    }
  }

  updateProgress(): void {
    if (!this.proposals || this.proposals.length === 0) {
      this.progressPct = 0;
    } else {
      this.progressPct = (this.index / this.proposals.length) * 100;
    }
  }

  decide(decision: 'merge' | 'ignore'): void {
    if (!this.current) return;
    const currentProposal = this.current;

    if (decision === 'merge') {
      this.merge.emit({ a: currentProposal.skuA, b: currentProposal.skuB });
      this.mergedCount++;
      this.actionHistory.push({ type: 'merge', proposal: currentProposal });
    } else {
      this.ignoredCount++;
      this.actionHistory.push({ type: 'ignore', proposal: currentProposal });
    }

    this.index++;
    if (this.index >= this.proposals.length) {
      this.complete.emit({ merged: this.mergedCount, ignored: this.ignoredCount });
    } else {
      this.current = this.proposals[this.index];
      this.updateProgress();
    }
  }

  undoAction(action: ActionHistory): void {
    const actionIdx = this.actionHistory.indexOf(action);
    if (actionIdx === -1) return;

    if (action.type === 'merge') {
      this.mergedCount = Math.max(0, this.mergedCount - 1);
    } else {
      this.ignoredCount = Math.max(0, this.ignoredCount - 1);
    }

    this.actionHistory.splice(actionIdx, 1);
    this.proposals.splice(this.index, 0, action.proposal);
    this.current = this.proposals[this.index];
    this.updateProgress();
  }

  exitTinder(): void {
    this.complete.emit({ merged: this.mergedCount, ignored: this.ignoredCount });
  }

  formatVND(value: number): string {
    if (!value) return '0 ₫';
    return Math.round(value).toLocaleString('vi-VN') + ' ₫';
  }
}
