package com.nemocraft;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

public class BackendClient {
        private static final String BACKEND_URL = "http://localhost:8000";
        private static final HttpClient CLIENT = HttpClient.newBuilder()
                        .connectTimeout(Duration.ofSeconds(10))
                        .version(HttpClient.Version.HTTP_1_1)
                        .build();
        private static final Gson GSON = new Gson();

        public static CompletableFuture<JsonObject> requestBuild(String prompt, String playerName,
                        double x, double y, double z, String biome) {
                JsonObject body = new JsonObject();
                body.addProperty("prompt", prompt);
                body.addProperty("player_name", playerName);
                body.addProperty("x", x);
                body.addProperty("y", y);
                body.addProperty("z", z);
                body.addProperty("biome", biome);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/build"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(120))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> checkAutoGenerate(String playerUuid, double x, double y, double z) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.addProperty("x", x);
                body.addProperty("y", y);
                body.addProperty("z", z);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/check"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(30))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> sendStats(String playerUuid, Map<String, Object> stats) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.add("stats", GSON.toJsonTree(stats));

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/stats"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(15))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        // -- Quest endpoints --------------------------------------------------

        public static CompletableFuture<JsonObject> generateQuests(String playerUuid, String playerName,
                        double x, double y, double z) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.addProperty("player_name", playerName);
                body.addProperty("x", x);
                body.addProperty("y", y);
                body.addProperty("z", z);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/quests/generate"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(60))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> listQuests(String playerUuid) {
                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/quests/" + playerUuid))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(15))
                                .GET()
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> acceptQuest(String playerUuid, String questId) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.addProperty("quest_id", questId);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/quests/accept"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(15))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> sendQuestProgress(String playerUuid,
                        String objectiveType, String target, int count) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.addProperty("objective_type", objectiveType);
                body.addProperty("target", target);
                body.addProperty("count", count);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/quests/progress"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(15))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }

        public static CompletableFuture<JsonObject> completeQuest(String playerUuid, String questId,
                        double x, double y, double z) {
                JsonObject body = new JsonObject();
                body.addProperty("player_uuid", playerUuid);
                body.addProperty("quest_id", questId);
                body.addProperty("x", x);
                body.addProperty("y", y);
                body.addProperty("z", z);

                HttpRequest request = HttpRequest.newBuilder()
                                .uri(URI.create(BACKEND_URL + "/api/quests/complete"))
                                .header("Content-Type", "application/json")
                                .timeout(Duration.ofSeconds(120))
                                .POST(HttpRequest.BodyPublishers.ofString(GSON.toJson(body)))
                                .build();

                return CLIENT.sendAsync(request, HttpResponse.BodyHandlers.ofString())
                                .thenApply(response -> GSON.fromJson(response.body(), JsonObject.class));
        }
}
