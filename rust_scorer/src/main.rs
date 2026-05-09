use actix_web::{post, web, App, HttpResponse, HttpServer, Responder};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
struct ScoreRequest {
    uncertainty: f64,
    max_active_requests: i32,
    weights: RoutingWeights,
    nodes: Vec<NodeInput>,
}

#[derive(Debug, Deserialize)]
struct RoutingWeights {
    alpha: f64,
    beta: f64,
    gamma: f64,
    delta: f64,
}

#[derive(Debug, Deserialize)]
struct NodeInput {
    node_url: String,
    kv_used_mb: i32,
    kv_capacity_mb: i32,
    active_requests: i32,
    healthy: bool,
    stale: bool,
}

#[derive(Debug, Serialize)]
struct ScoreResponse {
    ranked_nodes: Vec<NodeScore>,
}

#[derive(Debug, Serialize)]
struct NodeScore {
    node_url: String,
    free_kv_ratio: f64,
    cache_pressure: f64,
    load_ratio: f64,
    uncertainty: f64,
    stale_penalty: f64,
    score: f64,
    healthy: bool,
    stale: bool,
}

fn clamp01(value: f64) -> f64 {
    value.max(0.0).min(1.0)
}

#[post("/score")]
async fn score(req: web::Json<ScoreRequest>) -> impl Responder {
    let mut ranked_nodes: Vec<NodeScore> = req
        .nodes
        .iter()
        .map(|node| {
            let capacity = if node.kv_capacity_mb <= 0 { 1 } else { node.kv_capacity_mb };
            let used = node.kv_used_mb.max(0).min(capacity);

            let free_kv_ratio = (capacity - used) as f64 / capacity as f64;
            let cache_pressure = used as f64 / capacity as f64;
            let load_ratio = if req.max_active_requests <= 0 {
                node.active_requests as f64
            } else {
                clamp01(node.active_requests as f64 / req.max_active_requests as f64)
            };
            let stale_penalty = if node.stale { 1.0 } else { 0.0 };

            let score = req.weights.alpha * free_kv_ratio
                - req.weights.beta * load_ratio
                - req.weights.gamma * req.uncertainty * cache_pressure
                - req.weights.delta * stale_penalty;

            NodeScore {
                node_url: node.node_url.clone(),
                free_kv_ratio,
                cache_pressure,
                load_ratio,
                uncertainty: req.uncertainty,
                stale_penalty,
                score,
                healthy: node.healthy,
                stale: node.stale,
            }
        })
        .collect();

    ranked_nodes.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());

    HttpResponse::Ok().json(ScoreResponse { ranked_nodes })
}

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    println!("Rust scorer listening on 0.0.0.0:9000");

    HttpServer::new(|| App::new().service(score))
        .bind(("0.0.0.0", 9000))?
        .run()
        .await
}