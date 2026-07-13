"""Mastodon post analyzer - engagement patterns and content quality."""
import re
from collections import defaultdict
from datetime import datetime


def _categorize_post(text: str) -> str:
    """Categorize a post by its content type."""
    text_lower = text.lower()
    
    # Check for version/feature posts
    if re.search(r'v\d+\.\d+\.\d+|version \d+|fix(ed|ing)?|changelog', text_lower):
        return 'features'
    
    # Check for jokes (usually contain "why" questions or punchlines)
    if re.search(r'why.*because|what do you call|joke|humor', text_lower):
        return 'jokes'
    
    # Check for facts
    if re.search(r'did you know|fact|trivia|midi history', text_lower):
        return 'facts'
    
    # Check for creative uses
    if re.search(r'control|automat|use case|build|diy|project', text_lower):
        return 'creative_uses'
    
    # Check for history
    if re.search(r'198[0-9]|199[0-9]|200[0-9]|dave smith|kakehashi|yamaha|original midi', text_lower):
        return 'history'
    
    # Check for quick tips
    if re.search(r'tip|keep|invest|cable|connection|sync', text_lower):
        return 'quick_tips'
    
    # Check for behind the code
    if re.search(r'we fixed|we chased|we started|developer|code|bug', text_lower):
        return 'behind_the_code'
    
    return 'other'


def analyze_posts(statuses: list) -> None:
    """Analyze engagement patterns and content performance.
    
    Args:
        statuses: List of status dicts from mastodon_client.fetch_statuses()
    """
    if not statuses:
        print("No posts to analyze.")
        return
    
    # Parse dates and categorize
    categorized = defaultdict(list)
    engagement_data = []
    
    for status in statuses:
        # Parse timestamp
        try:
            created_at = status.get('created_at', '')
            if isinstance(created_at, str):
                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            else:
                dt = datetime.now()
        except (ValueError, AttributeError, TypeError):
            dt = datetime.now()
        
        # Calculate total engagement
        total_engagement = (
            status.get('reblogs_count', 0) +
            status.get('favourites_count', 0) +
            status.get('replies_count', 0)
        )
        
        # Strip HTML for categorization
        text = re.sub(r'<[^>]+>', '', status['content'])
        category = _categorize_post(text)
        
        categorized[category].append({
            'status': status,
            'datetime': dt,
            'engagement': total_engagement,
            'text': text,
            'has_media': len(status.get('media_attachments', [])) > 0,
        })
        
        engagement_data.append({
            'category': category,
            'engagement': total_engagement,
            'datetime': dt,
            'has_media': len(status.get('media_attachments', [])) > 0,
            'text': text[:200],
        })
    
    # Calculate metrics
    total_posts = len(statuses)
    total_engagement = sum(e['engagement'] for e in engagement_data)
    avg_engagement = total_engagement / total_posts if total_posts > 0 else 0
    
    # Date range
    dates = [e['datetime'] for e in engagement_data]
    date_range = (min(dates), max(dates)) if dates else (None, None)
    
    # Print analysis
    print("=" * 70)
    print("MASTODON POST ANALYSIS")
    print("=" * 70)
    print()
    print(f"Total Posts Analyzed: {total_posts}")
    print(f"Date Range: {date_range[0].strftime('%Y-%m-%d')} to {date_range[1].strftime('%Y-%m-%d')}")
    print()
    
    # Engagement Summary
    print("ENGAGEMENT SUMMARY")
    print("-" * 70)
    total_likes = sum(s.get('favourites_count', 0) for s in statuses)
    total_reblogs = sum(s.get('reblogs_count', 0) for s in statuses)
    total_replies = sum(s.get('replies_count', 0) for s in statuses)
    
    print(f"Total Engagement: {total_engagement}")
    print(f"  - Likes: {total_likes}")
    print(f"  - Reblogs: {total_reblogs}")
    print(f"  - Replies: {total_replies}")
    print(f"Average per Post: {avg_engagement:.2f}")
    print()
    
    # Top 10 Posts
    print("TOP 10 POSTS BY ENGAGEMENT")
    print("-" * 70)
    sorted_posts = sorted(engagement_data, key=lambda x: x['engagement'], reverse=True)[:10]
    
    for i, post in enumerate(sorted_posts, 1):
        dt = post['datetime'].strftime('%Y-%m-%d %H:%M')
        text_preview = post['text'][:100].replace('\n', ' ')
        if len(post['text']) > 100:
            text_preview += "..."
        print(f"{i}. [{dt}] {post['engagement']} engagement - {text_preview}")
    print()
    
    # Content Breakdown
    print("CONTENT BREAKDOWN")
    print("-" * 70)
    
    category_stats = {}
    for category, posts in categorized.items():
        count = len(posts)
        total_cat_engagement = sum(p['engagement'] for p in posts)
        avg_cat_engagement = total_cat_engagement / count if count > 0 else 0
        media_count = sum(1 for p in posts if p['has_media'])
        
        category_stats[category] = {
            'count': count,
            'percentage': (count / total_posts) * 100,
            'avg_engagement': avg_cat_engagement,
            'total_engagement': total_cat_engagement,
            'media_count': media_count,
        }
        
        print(f"{category}: {count} posts ({(count / total_posts) * 100:.1f}%) - "
              f"Avg engagement: {avg_cat_engagement:.2f}")
    print()
    
    # Media Analysis
    print("MEDIA ANALYSIS")
    print("-" * 70)
    posts_with_media = [e for e in engagement_data if e['has_media']]
    posts_without_media = [e for e in engagement_data if not e['has_media']]
    
    media_count = len(posts_with_media)
    no_media_count = len(posts_without_media)
    
    if media_count > 0:
        avg_media_engagement = sum(e['engagement'] for e in posts_with_media) / media_count
    else:
        avg_media_engagement = 0
    
    if no_media_count > 0:
        avg_no_media_engagement = sum(e['engagement'] for e in posts_without_media) / no_media_count
    else:
        avg_no_media_engagement = 0
    
    print(f"Posts with media: {media_count} ({(media_count / total_posts) * 100:.1f}%)")
    print(f"  - Avg engagement: {avg_media_engagement:.2f}")
    print(f"Posts without media: {no_media_count} ({(no_media_count / total_posts) * 100:.1f}%)")
    print(f"  - Avg engagement: {avg_no_media_engagement:.2f}")
    
    if avg_media_engagement > 0 and avg_no_media_engagement > 0:
        ratio = avg_media_engagement / avg_no_media_engagement
        print(f"Media posts perform {ratio:.1f}x better")
    print()
    
    # Time Analysis
    print("TIME ANALYSIS")
    print("-" * 70)
    hour_engagement = defaultdict(list)
    day_engagement = defaultdict(list)
    
    for post in engagement_data:
        hour = post['datetime'].hour
        day = post['datetime'].strftime('%A')
        hour_engagement[hour].append(post['engagement'])
        day_engagement[day].append(post['engagement'])
    
    # Best hours
    avg_by_hour = {h: sum(e)/len(e) for h, e in hour_engagement.items() if e}
    if avg_by_hour:
        best_hour = max(avg_by_hour, key=avg_by_hour.get)
        print(f"Best posting hour: {best_hour:02d}:00 (avg {avg_by_hour[best_hour]:.2f} engagement)")
    
    # Best days
    avg_by_day = {d: sum(e)/len(e) for d, e in day_engagement.items() if e}
    if avg_by_day:
        best_day = max(avg_by_day, key=avg_by_day.get)
        print(f"Best posting day: {best_day} (avg {avg_by_day[best_day]:.2f} engagement)")
    print()
    
    # Insights and Recommendations
    print("INSIGHTS & RECOMMENDATIONS")
    print("-" * 70)
    
    # Find best and worst performing categories
    if category_stats:
        best_cat = max(category_stats, key=lambda x: category_stats[x]['avg_engagement'])
        worst_cat = min(category_stats, key=lambda x: category_stats[x]['avg_engagement'])
        
        print(f"• Best performing content: {best_cat} "
              f"(avg {category_stats[best_cat]['avg_engagement']:.2f} engagement)")
        print(f"• Lowest performing content: {worst_cat} "
              f"(avg {category_stats[worst_cat]['avg_engagement']:.2f} engagement)")
    
    # Variety analysis
    num_categories = len(categorized)
    if num_categories < 4:
        print(f"• ⚠️  Low content variety ({num_categories} categories). "
              "Consider diversifying content types to prevent audience fatigue.")
    else:
        print(f"• ✓ Good content variety ({num_categories} categories)")
    
    # Engagement quality
    if avg_engagement < 1:
        print(f"• ⚠️  Low average engagement ({avg_engagement:.2f}). "
              "Consider adjusting content strategy or posting times.")
    elif avg_engagement < 3:
        print(f"• ✓ Moderate engagement ({avg_engagement:.2f}). "
              "There's room for improvement.")
    else:
        print(f"• ✓ Strong engagement ({avg_engagement:.2f})")
    
    # Media recommendation
    if avg_media_engagement > avg_no_media_engagement * 1.5:
        print(f"• 💡 Media posts perform significantly better. "
              "Consider adding more images to feature announcements.")
    
    print()
    print("=" * 70)
