import { execSync } from "node:child_process";
import path from "node:path";
import { readFile } from "node:fs/promises";
import type { CliArgs } from "../types";
import { 
  normalizeGoogleModelId, 
  isGoogleImagen, 
  isGoogleMultimodal, 
  getGoogleImageSize,
  addAspectRatioToPrompt,
  buildPromptWithAspect,
  extractInlineImageData,
  extractPredictedImageData
} from "./google.ts";

export function getDefaultModel(): string {
  return process.env.VERTEX_IMAGE_MODEL || "gemini-3-pro-image-preview";
}

async function getAccessToken(): Promise<string> {
  if (process.env.VERTEX_ACCESS_TOKEN) return process.env.VERTEX_ACCESS_TOKEN;
  
  try {
    // Attempt to use gcloud if available
    return execSync("gcloud auth print-access-token", { encoding: "utf8", stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch (err) {
    throw new Error("Failed to get Vertex access token. Please set VERTEX_ACCESS_TOKEN or ensure 'gcloud auth application-default login' is done.");
  }
}

function getVertexConfig() {
  const projectId = process.env.VERTEX_PROJECT_ID || process.env.GOOGLE_CLOUD_PROJECT;
  const location = process.env.VERTEX_LOCATION || "global";
  if (!projectId) throw new Error("VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT is required for Vertex AI.");
  return { projectId, location };
}

async function postVertexJson<T>(
  model: string,
  method: string,
  body: unknown
): Promise<T> {
  const { projectId, location } = getVertexConfig();
  const token = await getAccessToken();
  const modelId = normalizeGoogleModelId(model);
  
  // publisher is hardcoded to google for gemini/imagen
  const host = location === "global" ? "aiplatform.googleapis.com" : `${location}-aiplatform.googleapis.com`;
  const url = `https://${host}/v1beta1/projects/${projectId}/locations/${location}/publishers/google/models/${modelId}:${method}`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const errText = await res.text();
    let errMsg = errText;
    try {
      const parsed = JSON.parse(errText);
      if (parsed.error?.message) errMsg = parsed.error.message;
    } catch {
      // ignore
    }
    throw new Error(`Vertex AI API error (${res.status}): ${errMsg}`);
  }

  return (await res.json()) as T;
}

async function readImageAsBase64(p: string): Promise<{ data: string; mimeType: string }> {
  const buf = await readFile(p);
  const ext = path.extname(p).toLowerCase();
  let mimeType = "image/png";
  if (ext === ".jpg" || ext === ".jpeg") mimeType = "image/jpeg";
  else if (ext === ".gif") mimeType = "image/gif";
  else if (ext === ".webp") mimeType = "image/webp";
  return { data: buf.toString("base64"), mimeType };
}

async function generateWithGemini(
  prompt: string,
  model: string,
  args: CliArgs,
): Promise<Uint8Array> {
  const promptWithAspect = addAspectRatioToPrompt(prompt, args.aspectRatio);
  const parts: Array<{
    text?: string;
    inlineData?: { data: string; mimeType: string };
  }> = [];
  
  for (const refPath of args.referenceImages) {
    const { data, mimeType } = await readImageAsBase64(refPath);
    parts.push({ inlineData: { data, mimeType } });
  }
  parts.push({ text: promptWithAspect });

  const imageConfig = {
    imageSize: getGoogleImageSize(args),
  };

  console.error(`Generating image with Vertex Gemini (${model})...`);
  
  // Vertex uses streamGenerateContent for multimodal
  // Note: some regions might use generateContent, but stream is generally supported
  const response = await postVertexJson<any>(model, "generateContent", {
    contents: [
      {
        role: "user",
        parts,
      },
    ],
    generationConfig: {
      responseModalities: ["IMAGE"],
      imageConfig,
    },
  });

  // streamGenerateContent returns an array of chunks
  const chunks = Array.isArray(response) ? response : [response];
  for (const chunk of chunks) {
    const imageData = extractInlineImageData(chunk);
    if (imageData) return Uint8Array.from(Buffer.from(imageData, "base64"));
  }

  throw new Error("No image in Vertex Gemini response");
}

async function generateWithImagen(
  prompt: string,
  model: string,
  args: CliArgs,
): Promise<Uint8Array> {
  const fullPrompt = buildPromptWithAspect(prompt, args.aspectRatio, args.quality);
  const parameters: Record<string, unknown> = {
    sampleCount: args.n,
  };
  if (args.aspectRatio) {
    parameters.aspectRatio = args.aspectRatio;
  }
  
  const imageSize = getGoogleImageSize(args);
  if (imageSize === "1K" || imageSize === "2K") {
    parameters.imageSize = imageSize;
  } else {
    parameters.imageSize = "2K";
  }

  console.error(`Generating image with Vertex Imagen (${model})...`);

  const response = await postVertexJson<any>(model, "predict", {
    instances: [
      {
        prompt: fullPrompt,
      },
    ],
    parameters,
  });

  const imageData = extractPredictedImageData(response);
  if (imageData) return Uint8Array.from(Buffer.from(imageData, "base64"));

  throw new Error("No image in Vertex Imagen response");
}

export async function generateImage(
  prompt: string,
  model: string,
  args: CliArgs,
): Promise<Uint8Array> {
  if (isGoogleImagen(model)) {
    return generateWithImagen(prompt, model, args);
  }
  return generateWithGemini(prompt, model, args);
}