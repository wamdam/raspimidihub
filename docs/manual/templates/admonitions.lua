-- Map fenced-div classes to LaTeX admonition environments.
--
-- Markdown:    ::: note
--              ...body...
--              :::
--
-- LaTeX out:   \begin{note}
--              ...body...
--              \end{note}
--
-- The LaTeX envs `note`, `warning`, `tip` are defined in
-- templates/header.tex.
--
-- Wired in via `--lua-filter=templates/admonitions.lua` from the
-- `make manual` target.

local admonition_classes = {
  note = true,
  warning = true,
  tip = true,
}

function Div(el)
  for _, cls in ipairs(el.classes) do
    if admonition_classes[cls] then
      local opening = pandoc.RawBlock("latex", "\\begin{" .. cls .. "}")
      local closing = pandoc.RawBlock("latex", "\\end{" .. cls .. "}")
      local out = { opening }
      for _, blk in ipairs(el.content) do
        table.insert(out, blk)
      end
      table.insert(out, closing)
      return out
    end
  end
  return nil
end
