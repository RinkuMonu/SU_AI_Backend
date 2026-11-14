from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class BlogBase(BaseModel):
    title: str = Field(..., description="Blog post title")
    slug: Optional[str] = Field(None, description="URL-friendly SEO slug")
    category: str = Field(default="Business Growth", description="Category of the blog")
    excerpt: str = Field(..., description="Short summary/excerpt of the post")
    content: str = Field(..., description="Full markdown/html content of the blog")
    cover_image: Optional[str] = Field(None, description="Cover image URL")
    author: Optional[str] = Field(default="DhandaGrow Editorial", description="Author name")
    author_role: Optional[str] = Field(default="Growth Specialist", description="Author title/role")
    read_time: Optional[str] = Field(default="5 min read", description="Estimated read time")
    tags: Optional[List[str]] = Field(default_factory=list, description="Keywords/tags")
    published: bool = Field(default=True, description="Publish status")
    featured: bool = Field(default=False, description="Whether this post is featured on homepage")
    seo_title: Optional[str] = Field(None, description="Custom SEO title")
    seo_description: Optional[str] = Field(None, description="Custom SEO meta description")

class BlogCreate(BlogBase):
    pass

class BlogUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None
    cover_image: Optional[str] = None
    author: Optional[str] = None
    author_role: Optional[str] = None
    read_time: Optional[str] = None
    tags: Optional[List[str]] = None
    published: Optional[bool] = None
    featured: Optional[bool] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None

class BlogPostResponse(BlogBase):
    id: str
    views: int = 0
    likes: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

