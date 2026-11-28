# 第6回 解答

## 演習

<!-- [tool call] の行は、表示された行をそのまま貼り付けてください。終わらなかった STEP は、空欄のままでかまいません。 -->

- STEP 1 のツールの名前：
  - search_materials
  - glossary_search_glossary
- STEP 2 の [tool call]： [tool call]   glossary_search_glossary({'query': '3レベル'})
- STEP 3 の [tool call]： [tool call]   fetch_fetch({'url': 'https://modelcontextprotocol.io/'})
- STEP 4 の [tool call]：
  - [tool call]   aws_aws___search_documentation({'search_phrase': 'Amazon S3 バージョニング 概要'})
  - [tool call]   aws_aws___search_documentation({'topics': ['general', 'reference_documentation'], 'search_phrase': '"What is versioning" Amazon S3'})
- 気づき・疑問：
  - エージェントが MCP サーバーを使用する際、基本的にはユーザーからのクエリーに近い自然言語で問い合わせるのではなく、単語やそれに近いものでしか検索しない点が気になった。
  - MCP サーバーに問い合わせるときにエージェントが使用する引数はエージェントが決めるため、機密情報がクエリーに載っていても気づくことが困難な点には注意が必要だと感じた。自分が使用している　MCP サーバーを意識できているときはそのような質問自体を回避する意識を持つ事もできるが、実際にはエディタなどに組み込んだ場合は社内用のMCPサーバーも外部向けのMCPサーバーも同時にアクティブにする可能性があるので、そうしたクエリーが外部サーバーに対して混入しても不思議ではない状況も考えられる。この点には何等かの技術的な手立てがあってもよいと感じる。

## 宿題

<!-- 基礎・実装・発展のどれか1つに取り組めば完了です。 -->

- 取り組んだレベル： 発展

## やったこと：

- Claude Code の MCP サーバーの設定方法を調査する
- Claude Code の MCP サーバーの設定のバリエーションを調査する
- 演習の MCP サーバーの設定との比較
- Agent Plugins Specification との比較

## 結果：Claude Code の MCP サーバーの追加方法

### Claude Code の MCP サーバーの設定方法を調査する

#### オプション1: HTTPプロトコル

- リモートで運用されている MCP サーバーを追加する方法の一つ。
- トランスポートプロトコルが HTTP のものを設定。
- HTTP ヘッダーを指定できるため、トークンを設定することも可能。
- 参照: https://code.claude.com/docs/ja/mcp#option-1-add-a-remote-http-server

```
# Basic syntax
claude mcp add --transport http <name> <url>

# Real example: Connect to Notion
claude mcp add --transport http notion https://mcp.notion.com/mcp

# Example with Bearer token
claude mcp add --transport http secure-api https://api.example.com/mcp \
  --header "Authorization: Bearer your-token"
```

#### オプション2: SSEプロトコル

- 現在は非推奨である SSE プロトコルの MCP サーバーを追加する方法。
- やはりリモートで運用されているサーバーを追加する方法の一つ。
- HTTP ヘッダーを指定できるため、トークンを設定することも可能。
- 参照: https://code.claude.com/docs/ja/mcp#option-2-add-a-remote-sse-server

```
# Basic syntax
claude mcp add --transport sse <name> <url>

# Real example: Connect to Asana
claude mcp add --transport sse asana https://mcp.asana.com/sse

# Example with authentication header
claude mcp add --transport sse private-api https://api.company.com/sse \
  --header "X-API-Key: your-key-here"
```

#### オプション3: stdio プロトコル

- マシン上のローカルプロセスとして起動される MCP サーバーには、stdio プロトコルで接続。
- `--` のあとに `npx` や `uvx` などパッケージマネージャーを指定することができる。
- 参照： https://code.claude.com/docs/ja/mcp#option-3-add-a-local-stdio-server

```
# Basic syntax
claude mcp add [options] <name> -- <command> [args...]

# Real example: Add Airtable server
claude mcp add --env AIRTABLE_API_KEY=YOUR_KEY --transport stdio airtable \
  -- npx -y airtable-mcp-server
```

#### JSON設定による追加

- MCP サーバーの JSON 設定が分かっている場合は、直接それを指定して設定を追加することも可能。
- 参照： https://code.claude.com/docs/ja/mcp#add-mcp-servers-from-json-configuration

```
# 基本的な構文
claude mcp add-json <name> '<json>'

# 例：JSON 設定を使用して HTTP サーバーを追加する
claude mcp add-json weather-api '{"type":"http","url":"https://api.weather.com/mcp","headers":{"Authorization":"Bearer token"}}'

# 例：JSON 設定を使用して stdio サーバーを追加する
claude mcp add-json local-weather '{"type":"stdio","command":"/path/to/weather-cli","args":["--api-key","abc123"],"env":{"CACHE_DIR":"/tmp"}}'

# 例：事前設定された OAuth 認証情報を使用して HTTP サーバーを追加する
claude mcp add-json my-server '{"type":"http","url":"https://mcp.example.com/mcp","oauth":{"clientId":"your-client-id","callbackPort":8080}}' --client-secret
```

### Claude Code の MCP サーバーの設定のバリエーションを調査する

- Claude Code では、MCP サーバーの設定をどのような範囲で有効にするかを選択することが可能
- その設定方法や設定の保存場所を調査
- トークンなどの機密情報の扱いについても調査

#### 設定の保存場所

- 参照: https://code.claude.com/docs/ja/mcp#mcp-installation-scopes

**ローカルスコープ**

- 特定のプロジェクトに関する MCP サーバーの設定を保存
- プロジェクトメンバーとは共有されない
- 設定は `~/.claude.json` に保存される

```
# ローカルスコープのサーバーを追加する（デフォルト）
claude mcp add --transport http stripe https://mcp.stripe.com

# ローカルスコープを明示的に指定する
claude mcp add --transport http stripe --scope local https://mcp.stripe.com
```

```
{
  "projects": {
    "/path/to/your/project": {
      "mcpServers": {
        "stripe": {
          "type": "http",
          "url": "https://mcp.stripe.com"
        }
      }
    }
  }
}
```

**プロジェクトスコープ**

- プロジェクトメンバーと MCP サーバーの設定を共有したい場合は、`--scope` オプションを指定
- 設定はプロジェクト直下の `.mcp.json` に保存される

```
# プロジェクトスコープのサーバーを追加する
claude mcp add --transport http shared-server --scope project https://example.com/mcp
```

この場合、下記のような設定ファイル`.mcp.json`が保存される。

```
{
  "mcpServers": {
    "shared-server": {
      "type": "http",
      "url": "https://example.com/mcp"
    }
  }
}
```

また、認証情報を直接埋め込むことなく、MCPサーバーの設定だけをメンバー間で共有するため、
環境変数の展開もサポートされている。

参考: https://code.claude.com/docs/ja/mcp#environment-variable-expansion-in-mcp-json

```
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```

**ユーザースコープ**

- プロジェクトに関係なく使用したい MCP サーバーの設定
- プロジェクトメンバーとは共有されないユーザー固有の設定
- 設定は `~/.claude.json` に保存される

```
# ユーザーサーバーを追加する
claude mcp add --transport http hubspot --scope user https://mcp.hubspot.com/anthropic
```

### 演習の MCP サーバー設定との違い

- 設定ファイルの書式自体は Claude Code のプロジェクトスコープの設定ファイルとほぼ同じ
- ただし Claude Code ではスコープによって格納されるファイルと書式が異なる
- Claude Code では CLI で設定の追加・削除などが可能なためプロプラム的な制御が容易

### Agent Plugsins Specification

- Agent Skills と MCP サーバー設定を共有フォーマットにパッケージするための仕様
- OpenAI が AWS・Cursor・GitHub・VS Code・Vercel とともに策定
- Claude Code の .mcp.json の書式はこれに準拠しているという正式な記述は見つけられなかったが、書き方を見る限りでは同じに見える
- この仕様でも環境変数の展開がサポートされている
- 参照：https://github.com/agentplugins/agent-plugins-spec/blob/main/spec/1.0.0.md

## 気づき・疑問：

- Claude Code の設定について調査している過程で Agent Plugins Specification という仕様が策定されていることを知った
- AI 界隈のこのような設定(Skill/MCPなど)は、乱立して収拾がつかなくなる前に標準化しようという動きが取られることが多いように感じた
- プロンプトインジェクションのリスクを発生させる可能性があるのは MCP サーバーだけでなく通常の Web サイトや単なるドキュメント、フリーソフトまで考えられてしまうので、抜本的な対策が困難であるという印象を受ける

