#!/usr/bin/env python3

import asyncio
import json
import sys
import os

# Add the backend directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from backend.app.agent import AgentMessage, process_agent_message

async def test_slack_date_handling():
    """Test that Slack summaries use correct dates."""
    
    print("🧪 Testing Slack date handling...")
    
    # Test requests with different date formats
    test_messages = [
        "Send a Slack summary for today",
        "Send a Slack summary for 2025-08-15", 
        "Send slack summary for tomorrow",
        "Can you send the appointment summary to Slack for today?"
    ]
    
    session_id = "test_slack_dates"
    
    for i, message in enumerate(test_messages):
        print(f"\n--- Test {i+1}: {message} ---")
        
        try:
            request = AgentMessage(
                message=message,
                session_id=session_id,
                user_type="doctor"
            )
            
            response = await process_agent_message(request)
            print(f"✅ Response: {response.text}")
            
            # Check if response contains date-related information
            if "2025" in response.text or "August" in response.text:
                print("✅ Date handling appears correct")
            elif "2024" in response.text or "June" in response.text:
                print("❌ Date handling may be incorrect - showing old dates")
            else:
                print("ℹ️  Response doesn't show specific dates")
            
        except Exception as e:
            print(f"❌ Error: {e}")
        
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(test_slack_date_handling())
