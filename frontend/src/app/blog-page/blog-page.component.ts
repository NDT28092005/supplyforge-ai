import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../api.service';

@Component({
  selector: 'app-blog-page',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './blog-page.component.html',
  styleUrls: ['./blog-page.component.css']
})
export class BlogPageComponent implements OnInit {
  posts: any[] = [];
  selectedArticle: any = null;
  loading = true;
  loadingArticle = false;

  constructor(private apiService: ApiService) {}

  ngOnInit(): void {
    this.apiService.getBlogPosts().subscribe({
      next: (res) => {
        this.posts = res.posts || [];
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load Blog Posts API:', err);
        this.loading = false;
      }
    });
  }

  readArticle(slug: string): void {
    this.loadingArticle = true;
    this.apiService.getBlogDetail(slug).subscribe({
      next: (res) => {
        this.selectedArticle = res;
        this.loadingArticle = false;
      },
      error: (err) => {
        console.error('Failed to load Blog Detail API:', err);
        this.loadingArticle = false;
      }
    });
  }

  backToList(): void {
    this.selectedArticle = null;
  }
}
