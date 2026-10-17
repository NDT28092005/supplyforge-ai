import { AfterViewInit, Directive, ElementRef, OnDestroy, inject } from '@angular/core';
import { PageMotionService } from './page-motion.service';

@Directive({
  selector: '[sfPageMotion]',
  standalone: true,
})
export class PageMotionDirective implements AfterViewInit, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);
  private readonly motion = inject(PageMotionService);
  private dispose?: () => void;

  ngAfterViewInit(): void {
    this.dispose = this.motion.reveal(this.host.nativeElement);
  }

  ngOnDestroy(): void {
    this.dispose?.();
  }
}
