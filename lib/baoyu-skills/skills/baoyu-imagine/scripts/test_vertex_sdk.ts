import { VertexAI } from '@google-cloud/vertexai';

async function test() {
  const vertexAI = new VertexAI({ 
    project: 'vertexcc-493408', 
    location: 'global' 
  });
  
  const model = vertexAI.getGenerativeModel({
    model: 'gemini-3.1-pro-preview',
  });
  
  console.log("Model ID:", model);
  // We can't easily see the URL without running it, but we can try to generate something small
  try {
    const result = await model.generateContent("hello");
    console.log("Success!");
  } catch (err) {
    console.error("Error:", err);
  }
}

test();