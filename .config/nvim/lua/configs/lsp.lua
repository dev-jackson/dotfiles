local status, nvim_lsp = pcall(require, "lspconfig")
if not status then
    return
end

local protocol = require("vim.lsp.protocol")

local on_attach = function(client, bufnr)
    -- format on save
    if client.server_capabilities.documentFormattingProvider then
        vim.api.nvim_create_autocmd("BufWritePre", {
            group = vim.api.nvim_create_augroup("Format", { clear = true }),
            buffer = bufnr,
            callback = function()
                vim.lsp.buf.format()
            end,
        })
    end
end

local capabilities = require("cmp_nvim_lsp").default_capabilities()

-- TypeScript
nvim_lsp.tsserver.setup({
    on_attach = on_attach,
    filetypes = { "typescript", "typescriptreact", "typescript.tsx" },
    cmd = { "typescript-language-server", "--stdio" },
    capabilities = capabilities,
})

-- CSS
nvim_lsp.cssls.setup({
    on_attach = on_attach,
    capabilities = capabilities,
})

-- Tailwind
nvim_lsp.tailwindcss.setup({
    on_attach = on_attach,
    capabilities = capabilities,
})

-- Emmet
nvim_lsp.emmet_ls.setup({
    on_attach = on_attach,
    capabilities = capabilities,
})

nvim_lsp.lua_ls.setup({
    on_attach = on_attach,
    settings = {
        Lua = {
            diagnostics = {
                globals = { 'vim' }
            },
            workspace = {
                library = vim.api.nvim_get_runtime_file("", true)
            }
        }
    }
})

-- Eslint
local eslint = {
    lintCommand = "eslint_d -f unix --stdin --stdin-filename ${INPUT}",
    lintIgnoreExitCode = true,
    lintStdin = true,
    lintFormats = { "%f:%l:%c: %m" },
    formatCommand = "eslint_d --fix-to-stdout --stdin --stdin-filename=${INPUT}",
    formatStdin = true
}

nvim_lsp.efm.setup({
    init_options = { documentFormatting = true, codeAction = true },
    settings = {
        languages = {
            javascript = { eslint },
            javascriptreact = { eslint },
            ["javascript.jsx"] = { eslint },
            typescript = { eslint },
            typescriptreact = { eslint }
        }
    },
    filetypes = {
        "javascript",
        "javascriptreact",
        "javascript.jsx",
        "typescript",
        "typescriptreact",
        "typescript.tsx"
    }
})

vim.cmd [[autocmd BufWritePre * lua vim.lsp.buf.format()]]
