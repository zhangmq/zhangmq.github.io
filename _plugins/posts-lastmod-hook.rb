# MIT License, Copyright (c) 2022 Cotes Chung
# Get the last modified time of a file and attach it to the post

Jekyll::Hooks.register :posts, :pre_render do |post|
  commit_num = `git rev-list --count HEAD "#{ post.path }" 2>/dev/null`.strip.to_i

  if commit_num > 0
    lastmod_date = `git log -1 --pretty="%ad" --date=iso "#{ post.path }" 2>/dev/null`.strip
    post.data["last_modified_at"] = lastmod_date
  end
end
