import { localBrowser, Stagehand } from "@browserbasehq/stagehand";
import OpenAI from "openai";
import { z } from "zod";
import dotenv from "dotenv";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const here = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(here, "../../.env") });
dotenv.config({ path: path.resolve(here, "../.env") });

const TASK_IDS = ["ecommerce_filter_extract", "form_auth_and_state", "media_spa_navigation", "github_repo_traversal"] as const;
type TaskId = (typeof TASK_IDS)[number];

// Must match the primary-monitor window placement used by the browser-use candidate.
const WINDOW_ARGS = ["--window-position=0,0", "--window-size=1536,864"];

type ContentBlock = { type: string; text?: string; data?: string; mimeType?: string };

function toOpenAIContent(content: ContentBlock | ContentBlock[]) {
  const blocks = Array.isArray(content) ? content : [content];
  return blocks.map((b) => {
    if (b.type === "text") return { type: "text" as const, text: b.text ?? "" };
    if (b.type === "image") return { type: "image_url" as const, image_url: { url: `data:${b.mimeType};base64,${b.data}` } };
    throw new Error(`Unsupported content block type: ${b.type}`);
  });
}

// Stagehand v4 only knows a fixed list of provider/model names; anything else goes through this callback.
function openAICompatibleGenerate(baseURL: string, apiKey: string, model: string) {
  const client = new OpenAI({ baseURL, apiKey });
  return async (params: any) => {
    const structured = params.responseFormat?.type === "json_schema";
    if (!structured && params.tools?.length) {
      throw new Error("Tool-calling requests are not supported by the OpenAI-compatible adapter");
    }
    const messages: any[] = [];
    if (params.systemPrompt) messages.push({ role: "system", content: params.systemPrompt });
    for (const m of params.messages) messages.push({ role: m.role, content: toOpenAIContent(m.content) });

    const response = await client.chat.completions.create({
      model,
      messages,
      temperature: params.temperature,
      stop: params.stopSequences,
      ...(structured
        ? {
            response_format: {
              type: "json_schema" as const,
              json_schema: { name: params.responseFormat.name, schema: params.responseFormat.schema, strict: true },
            },
          }
        : {}),
    });

    const text = response.choices[0].message.content ?? "";
    const usage = response.usage
      ? {
          inputTokens: response.usage.prompt_tokens,
          outputTokens: response.usage.completion_tokens,
          totalTokens: response.usage.total_tokens,
        }
      : undefined;
    const base = { role: "assistant" as const, content: { type: "text" as const, text }, usage };
    return structured
      ? { ...base, outputFormat: "json_schema" as const, structuredContent: JSON.parse(text) }
      : { ...base, outputFormat: "text" as const };
  };
}

function resolveModel(providerName: string): { model: any; modelLabel: string } {
  const env = process.env;
  const requireKey = (name: string) => {
    const value = env[name];
    if (!value || value.startsWith("your_")) throw new Error(`${name} is not set in .env`);
    return value;
  };

  switch (providerName) {
    case "cerebras": {
      const modelName = `cerebras/${env.CEREBRAS_MODEL || "gpt-oss-120b"}`;
      return { model: { modelName, apiKey: requireKey("CEREBRAS_API_KEY") }, modelLabel: modelName };
    }
    case "groq": {
      const modelName = `groq/${env.GROQ_MODEL || "openai/gpt-oss-20b"}`;
      return { model: { modelName, apiKey: requireKey("GROQ_API_KEY") }, modelLabel: modelName };
    }
    case "deepinfra": {
      const modelName = env.DEEPINFRA_MODEL || "Qwen/Qwen2.5-72B-Instruct";
      const generate = openAICompatibleGenerate("https://api.deepinfra.com/v1/openai", requireKey("DEEPINFRA_API_KEY"), modelName);
      return { model: { generate }, modelLabel: `deepinfra/${modelName}` };
    }
    case "ollama": {
      const modelName = env.OLLAMA_MODEL || "qwen2.5:3b";
      const baseURL = `${(env.OLLAMA_BASE_URL || "http://127.0.0.1:11434").replace(/\/$/, "")}/v1`;
      return { model: { generate: openAICompatibleGenerate(baseURL, "ollama", modelName) }, modelLabel: `ollama/${modelName}` };
    }
    default:
      throw new Error(`Unknown provider '${providerName}'. Use one of: cerebras, groq, deepinfra, ollama`);
  }
}

type TaskContext = {
  stagehand: Stagehand;
  page: Awaited<ReturnType<Stagehand["browser"]["context"]["newPage"]>>;
  step: (label: string) => void;
};

type TaskOutcome = { success: boolean; data: unknown };

const TASKS: Record<TaskId, { name: string; run: (ctx: TaskContext) => Promise<TaskOutcome> }> = {
  ecommerce_filter_extract: {
    name: "E-Commerce Category Filter & Deep Extraction",
    run: async ({ stagehand, page, step }) => {
      await page.goto("https://books.toscrape.com/");
      step("Navigated to books.toscrape.com");
      await stagehand.act("Click the 'Travel' category link in the left sidebar");
      step("Clicked Travel category");
      await stagehand.act("Click the book titled 'It's Only the Himalayas'");
      step("Opened book detail page");
      const { data } = await stagehand.extract(
        "Extract the book title, its price including the currency symbol, and the UPC from the product information table",
        z.object({ title: z.string(), price: z.string(), upc: z.string() }),
      );
      step("Extracted title, price and UPC");
      return { success: Boolean(data.upc), data };
    },
  },
  form_auth_and_state: {
    name: "Form Authentication & State Verification",
    run: async ({ stagehand, page, step }) => {
      await page.goto("https://the-internet.herokuapp.com/login");
      step("Navigated to login page");
      await stagehand.act("Type 'tomsmith' into the username field");
      step("Entered username");
      await stagehand.act("Type 'SuperSecretPassword!' into the password field");
      step("Entered password");
      await stagehand.act("Click the Login button");
      step("Clicked Login");
      const { data } = await stagehand.extract(
        "Extract the confirmation banner text shown at the top of the page, and whether the page is the secure area",
        z.object({ success: z.boolean(), message: z.string() }),
      );
      step("Extracted login confirmation");
      return { success: data.success && /secure area/i.test(data.message), data };
    },
  },
  media_spa_navigation: {
    name: "Dynamic SPA & Video Navigation",
    run: async ({ stagehand, page, step }) => {
      await page.goto("https://www.youtube.com");
      step("Navigated to YouTube");
      await stagehand.act("Type 'Lofi Girl relaxing beats' into the search box");
      step("Typed search query");
      await stagehand.act("Click the search button");
      step("Submitted search");
      await stagehand.act("Click the title of the first video in the search results");
      step("Opened first video");
      const { data } = await stagehand.extract(
        "Extract the title of the video that is currently playing",
        z.object({ video_title: z.string() }),
      );
      step("Extracted video title");
      const onWatchPage = (await page.url()).includes("/watch");
      return { success: onWatchPage && Boolean(data.video_title), data };
    },
  },
  github_repo_traversal: {
    name: "GitHub Issues Traversal & Multi-Item Extraction",
    run: async ({ stagehand, page, step }) => {
      await page.goto("https://github.com/microsoft/playwright");
      step("Navigated to repository");
      await stagehand.act("Click the 'Issues' tab in the repository navigation");
      step("Opened Issues tab");
      const { data } = await stagehand.extract(
        "Extract the issue number and title of the first 2 open issues in the list",
        z.object({ issues: z.array(z.object({ number: z.string(), title: z.string() })) }),
      );
      step("Extracted issues");
      return { success: data.issues.length >= 2, data };
    },
  },
};

async function runTask(taskId: TaskId, providerName: string) {
  const task = TASKS[taskId];
  const { model, modelLabel } = resolveModel(providerName);

  console.log("=======================================================");
  console.log(`Running Task: ${task.name} (${taskId})`);
  console.log(`Candidate: stagehand | Provider: ${providerName} | Model: ${modelLabel}`);
  console.log("=======================================================");

  const startTime = Date.now();
  let firstActionTime: number | null = null;
  let stepCount = 0;
  let success = false;
  let extractedData: unknown = null;
  let errorMessage: string | null = null;
  let tokens = { prompt: 0, completion: 0 };

  const browser = await localBrowser.launch({ headless: process.env.HEADLESS === "true", args: WINDOW_ARGS });
  let stagehand: Stagehand | undefined;

  try {
    stagehand = await Stagehand.create({ browser, model });
    const page = (await browser.context.activePage()) ?? (await browser.context.newPage());

    const step = (label: string) => {
      stepCount++;
      // First step is a plain navigation; TTFA is measured at the first LLM-driven step.
      if (stepCount === 2 && firstActionTime === null) {
        firstActionTime = Date.now();
        console.log(`[Telemetry] Time to First Action (TTFA): ${((firstActionTime - startTime) / 1000).toFixed(2)}s`);
      }
      console.log(`[Step ${stepCount}] ${label}`);
    };

    const outcome = await task.run({ stagehand, page, step });
    success = outcome.success;
    extractedData = outcome.data;
    console.log(`\n[Result] Task ${success ? "SUCCEEDED" : "FAILED"}`);
    console.log("[Output]:", JSON.stringify(extractedData));
  } catch (err: any) {
    errorMessage = err?.message || String(err);
    console.error(`\n[Result] Task ERROR: ${errorMessage}`);
  } finally {
    if (stagehand) {
      try {
        const m = await stagehand.metrics();
        tokens = { prompt: m.totalPromptTokens, completion: m.totalCompletionTokens };
      } catch {
        // metrics are best-effort; the run result still gets recorded
      }
      await stagehand.close();
    }
    await browser.close();
  }

  const result = {
    candidate: "stagehand",
    provider: providerName,
    model: modelLabel,
    task_id: taskId,
    task_name: task.name,
    success,
    total_duration_sec: (Date.now() - startTime) / 1000,
    time_to_first_action_sec: firstActionTime ? (firstActionTime - startTime) / 1000 : null,
    step_count: stepCount,
    prompt_tokens: tokens.prompt,
    completion_tokens: tokens.completion,
    total_tokens: tokens.prompt + tokens.completion,
    extracted_data: extractedData,
    error_message: errorMessage,
    timestamp: new Date().toISOString(),
  };

  const resultsDir = path.resolve(here, "../results");
  fs.mkdirSync(resultsDir, { recursive: true });
  const stamp = result.timestamp.replace(/[-:]/g, "").replace("T", "_").slice(0, 15);
  const resultPath = path.join(resultsDir, `${stamp}_stagehand_${taskId}.json`);
  fs.writeFileSync(resultPath, JSON.stringify(result, null, 2));
  console.log(`[Telemetry] Result logged to: ${resultPath}\n`);
}

async function main() {
  const taskArg = process.argv[2] || "form_auth_and_state";
  const providerName = process.argv[3] || "cerebras";
  const taskIds: TaskId[] = taskArg === "all" ? [...TASK_IDS] : [taskArg as TaskId];
  for (const id of taskIds) {
    if (!TASKS[id]) throw new Error(`Unknown task '${id}'. Use one of: ${TASK_IDS.join(", ")}, all`);
    await runTask(id, providerName);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
