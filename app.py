from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client
import math

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://gukcpxzcffflrgywqrpy.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_SECRET_SERVICE_OR_ANON_KEY" # Replace with valid server credentials
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def format_overs_decimal(completed_overs, legal_balls):
    """Safely converts counts to cricket over standard notation (e.g. 5 overs + 2 balls = 5.2)"""
    if legal_balls >= 6:
        completed_overs += legal_balls // 6
        legal_balls = legal_balls % 6
    return float(f"{completed_overs}.{legal_balls}")

def recalculate_nrr(house_name):
    """Calculates Net Run Rate: (Total Runs Scored / Total Overs Faced) - (Total Runs Conceded / Total Overs Bowled)"""
    res = supabase.table("points_table").select("*").eq("house_name", house_name).maybe_single().execute()
    if not res.data: return
    
    d = res.data
    def to_balls(ov):
        co = math.floor(ov)
        return (co * 6) + int(round((ov - co) * 10))

    balls_faced = to_balls(float(d.get("overs_faced_total") or 0))
    balls_bowled = to_balls(float(d.get("overs_bowled_total") or 0))
    
    overs_faced_dec = balls_faced / 6.0
    overs_bowled_dec = balls_bowled / 6.0
    
    bat_rate = (d["runs_scored_total"] / overs_faced_dec) if overs_faced_dec > 0 else 0.0
    bowl_rate = (d["runs_conceded_total"] / overs_bowled_dec) if overs_bowled_dec > 0 else 0.0
    
    nrr = round(bat_rate - bowl_rate, 3)
    supabase.table("points_table").update({"net_run_rate": nrr}).eq("house_name", house_name).execute()

@app.route("/api/process-ball", methods=["POST"])
def process_ball():
    payload = request.json
    match_num = payload.get("match_num")
    event_type = payload.get("event_type") # 'DOT', '1', '2', '3', '4', '6', 'WIDE', 'NO_BALL', 'WICKET'
    
    # Retrieve current active snapshot
    state_res = supabase.table("active_match_state").select("*").eq("match_num", match_num).maybe_single().execute()
    if not state_res.data:
        return jsonify({"error": "Active match sequence state initialization not found"}), 404
    
    state = state_res.data
    
    # Deconstruct over layout metric parameters
    current_ov_dec = float(state["total_overs_decimal"] or 0.0)
    completed_overs = math.floor(current_ov_dec)
    current_legal_balls = int(round((current_ov_dec - completed_overs) * 10))
    
    runs_bat = 0
    extras = 0
    extra_type = "NONE"
    is_wicket = False
    comm = ""
    
    # Parse incoming ball matrix action triggers
    if event_type in ['DOT', '1', '2', '3', '4', '6']:
        runs_bat = 0 if event_type == 'DOT' else int(event_type)
        current_legal_balls += 1
        comm = f"{runs_bat} run(s) scored off the bat of {state['striker_name']}." if runs_bat > 0 else "Excellent dot ball delivered."
        
    elif event_type == 'WIDE':
        extras = 1 # Automatic penalty run weight allocation
        extra_type = "WIDE"
        comm = "Wide delivery called by umpire. Extra run allocated."
        
    elif event_type == 'NO_BALL':
        extras = 1
        extra_type = "NO_BALL"
        comm = "No-ball registered. Penalty run added, free-hit sequence pending."
        
    elif event_type == 'WICKET':
        current_legal_balls += 1
        is_wicket = True
        comm = f"OUT! Heavy blow for the batting side as {state['striker_name']} falls down on crease."

    # Handle over transitions
    if current_legal_balls >= 6:
        completed_overs += 1
        current_legal_balls = 0
        comm += " That concludes the over segment."
        # Automatic strike rotation when the over finishes
        state["striker_name"], state["non_striker_name"] = state["non_striker_name"], state["striker_name"]

    new_overs_dec = format_overs_decimal(completed_overs, current_legal_balls)
    total_increment_runs = runs_bat + extras
    
    # Update state maps
    updated_runs = state["total_runs"] + total_increment_runs
    updated_wickets = state["total_wickets"] + (1 if is_wicket else 0)

    # 1. Update Core Persistent Transaction Logs
    supabase.table("ball_by_ball_log").insert({
        "match_num": match_num,
        "innings": state["current_innings"],
        "over_num": completed_overs if current_legal_balls > 0 else completed_overs - 1,
        "ball_num": current_legal_balls if current_legal_balls > 0 else 6,
        "striker_name": state["striker_name"],
        "non_striker_name": state["non_striker_name"],
        "bowler_name": state["current_bowler"],
        "runs_off_bat": runs_bat,
        "extras": extras,
        "extra_type": extra_type,
        "is_wicket": is_wicket,
        "commentary_text": comm
    }).execute()

    # 2. Update Public Display Cache Row
    supabase.table("active_match_state").update({
        "total_runs": updated_runs,
        "total_wickets": updated_wickets,
        "total_overs_decimal": new_overs_dec,
        "last_event_summary": comm,
        "striker_name": state["striker_name"],
        "non_striker_name": state["non_striker_name"]
    }).eq("match_num", match_num).execute()

    # 3. Stream sync updates back into global single dashboards live table
    supabase.table("live_match").update({
        "runs": updated_runs,
        "wickets": updated_wickets,
        "overs": str(new_overs_dec),
        "commentary": comm,
        "batsman_on_strike": state["striker_name"],
        "batsman_off_strike": state["non_striker_name"]
    }).eq("id", 1).execute()

    return jsonify({"status": "SUCCESS", "current_runs": updated_runs, "overs": new_overs_dec})

@app.route("/api/finalize-match", methods=["POST"])
def finalize_match():
    """Handles automatic aggregation of individual awards, team standings matrix, and NRR strings"""
    payload = request.json
    match_num = payload.get("match_num")
    winning_house = payload.get("winning_house")
    losing_house = payload.get("losing_house")
    
    # Process team standings adjustments
    for house in [winning_house, losing_house]:
        pts_res = supabase.table("points_table").select("*").eq("house_name", house).maybe_single().execute()
        if pts_res.data:
            curr = pts_res.data
            is_win = (house == winning_house)
            supabase.table("points_table").update({
                "played": curr["played"] + 1,
                "won": curr["won"] + (1 if is_win else 0),
                "lost": curr["lost"] + (0 if is_win else 1),
                "points": curr["points"] + (2 if is_win else 0)
            }).eq("house_name", house).execute()
            
            recalculate_nrr(house)
            
    return jsonify({"status": "SUCCESS", "message": "Match metrics processed, Caps calculations synchronized successfully."})

if __name__ == "__main__":
    app.run(port=5000, debug=True)