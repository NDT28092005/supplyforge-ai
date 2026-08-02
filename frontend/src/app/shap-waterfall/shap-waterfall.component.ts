import { Component, Input, OnInit, OnChanges, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';

interface ShapContribution {
  feature_name: string;
  feature_value: string;
  shap_value: number;
}

interface WaterfallStep {
  label: string;
  detail: string;
  start: number;
  end: number;
  value: number;
  type: 'base' | 'positive' | 'negative' | 'final';
  x: number;
  y: number;
  width: number;
  height: number;
}

@Component({
  selector: 'app-shap-waterfall',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './shap-waterfall.component.html',
  styleUrls: ['./shap-waterfall.component.css']
})
export class ShapWaterfallComponent implements OnInit, OnChanges {
  @Input() baseValue = 0.35;
  @Input() riskProbability = 0.35;
  @Input() contributions: ShapContribution[] = [];

  steps: WaterfallStep[] = [];
  svgWidth = 550;
  svgHeight = 310;
  paddingLeft = 190;
  paddingRight = 60;
  paddingTop = 25;
  paddingBottom = 45;

  tooltipText = '';
  tooltipX = 0;
  tooltipY = 0;
  showTooltip = false;

  ngOnInit(): void {
    this.generateWaterfall();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['baseValue'] || changes['riskProbability'] || changes['contributions']) {
      this.generateWaterfall();
    }
  }

  generateWaterfall(): void {
    const rawContributions = this.contributions || [];
    // Sort contributions by absolute value descending
    const sorted = [...rawContributions].sort((a, b) => Math.abs(b.shap_value) - Math.abs(a.shap_value));
    
    const calculatedSteps: WaterfallStep[] = [];
    
    // Step height calculations
    const totalRows = sorted.length + 2; // Base + Features + Final
    const innerHeight = this.svgHeight - this.paddingTop - this.paddingBottom;
    const rowHeight = innerHeight / totalRows;
    const barHeight = Math.max(12, rowHeight * 0.55);

    // X-axis scaling helper
    const innerWidth = this.svgWidth - this.paddingLeft - this.paddingRight;
    const xScale = (val: number) => this.paddingLeft + val * innerWidth;

    // 1. Base Value Step (From 0% to Base Risk)
    calculatedSteps.push({
      label: 'Mức nền hệ thống (Base)',
      detail: `${(this.baseValue * 100).toFixed(0)}%`,
      start: 0,
      end: this.baseValue,
      value: this.baseValue,
      type: 'base',
      x: xScale(0),
      y: this.paddingTop + (rowHeight - barHeight) / 2,
      width: this.baseValue * innerWidth,
      height: barHeight
    });

    // 2. Additive Contribution Steps
    let cumulative = this.baseValue;
    sorted.forEach((item, index) => {
      const startVal = cumulative;
      const endVal = cumulative + item.shap_value;
      cumulative = endVal;

      const type = item.shap_value >= 0 ? 'positive' : 'negative';
      const xStart = xScale(Math.min(startVal, endVal));
      const width = Math.abs(item.shap_value) * innerWidth;
      const y = this.paddingTop + (index + 1) * rowHeight + (rowHeight - barHeight) / 2;

      calculatedSteps.push({
        label: item.feature_name,
        detail: `${item.feature_value} (${item.shap_value >= 0 ? '+' : ''}${(item.shap_value * 100).toFixed(1)}%)`,
        start: startVal,
        end: endVal,
        value: item.shap_value,
        type: type,
        x: xStart,
        y: y,
        width: Math.max(2, width), // ensure it remains visible
        height: barHeight
      });
    });

    // 3. Final Prediction Risk (From 0% to Final Probability)
    const finalY = this.paddingTop + (totalRows - 1) * rowHeight + (rowHeight - barHeight) / 2;
    calculatedSteps.push({
      label: 'Xác suất rủi ro dự báo',
      detail: `${(this.riskProbability * 100).toFixed(0)}%`,
      start: 0,
      end: this.riskProbability,
      value: this.riskProbability,
      type: 'final',
      x: xScale(0),
      y: finalY,
      width: this.riskProbability * innerWidth,
      height: barHeight
    });

    this.steps = calculatedSteps;
  }

  getConnectorPath(step: WaterfallStep, nextStep: WaterfallStep): string {
    // Determine the end X-coordinate of the current step
    const currentEndX = step.type === 'base' || step.type === 'final'
      ? step.x + step.width
      : (step.value >= 0 ? step.x + step.width : step.x);

    // Determine the start X-coordinate of the next step
    const nextStartX = nextStep.type === 'base' || nextStep.type === 'final'
      ? nextStep.x + nextStep.width
      : (nextStep.value >= 0 ? nextStep.x : nextStep.x + nextStep.width);

    const yStart = step.y + step.height / 2;
    const yEnd = nextStep.y + nextStep.height / 2;

    return `M ${currentEndX} ${yStart} L ${currentEndX} ${yEnd} L ${nextStartX} ${yEnd}`;
  }

  onHoverBar(event: MouseEvent, step: WaterfallStep): void {
    this.tooltipText = `${step.label}: ${step.detail}`;
    this.tooltipX = event.offsetX + 15;
    this.tooltipY = event.offsetY - 25;
    this.showTooltip = true;
  }

  onLeaveBar(): void {
    this.showTooltip = false;
  }

  getTickValues(): number[] {
    return [0.0, 0.2, 0.4, 0.6, 0.8, 1.0];
  }

  getTickX(val: number): number {
    const innerWidth = this.svgWidth - this.paddingLeft - this.paddingRight;
    return this.paddingLeft + val * innerWidth;
  }
}
