import { Component } from '@angular/core';
import { RouterModule } from '@angular/router';

import { PageMotionDirective } from '../core/motion/page-motion.directive';

@Component({
  selector: 'app-not-found-page',
  standalone: true,
  imports: [RouterModule, PageMotionDirective],
  templateUrl: './not-found-page.component.html',
  styleUrls: ['./not-found-page.component.css']
})
export class NotFoundPageComponent {}
