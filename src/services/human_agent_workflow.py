"""Human agent workflow service for assignment, queue management, and response injection."""
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import json
import asyncio

from src.core.database import supabase
from src.core.config import settings

logger = logging.getLogger(__name__)


class HumanAgentWorkflowService:
    """Service for managing human agent workflows."""
    
    def __init__(self):
        self.max_queue_timeout = 30  # minutes
        
    async def assign_conversation_to_agent(
        self, 
        conversation_id: str, 
        agent_id: Optional[str] = None,
        assignment_type: str = "automatic",
        priority: str = "normal",
        assigned_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Assign a conversation to an available agent."""
        try:
            logger.info(f"Assigning conversation {conversation_id} to agent {agent_id}")
            
            # Get conversation details
            conv_result = supabase.table("conversations").select("*").eq("id", conversation_id).single().execute()
            if not conv_result.data:
                raise ValueError("Conversation not found")
            
            conversation = conv_result.data
            
            # If no specific agent requested, find the best available agent
            if not agent_id:
                agent_id = await self._find_best_available_agent(conversation["org_id"], conversation["kb_id"])
                if not agent_id:
                    # Add to queue if no agent available
                    return await self._add_to_queue(conversation_id, conversation, priority)
            
            # Verify agent is available
            agent_available = await self._check_agent_availability(agent_id)
            if not agent_available:
                logger.warning(f"Agent {agent_id} is not available")
                return await self._add_to_queue(conversation_id, conversation, priority)
            
            # Create assignment
            assignment_data = {
                "conv_id": conversation_id,
                "agent_id": agent_id,
                "assigned_by": assigned_by,
                "assignment_type": assignment_type,
                "priority": priority,
                "status": "active"
            }
            
            assignment_result = supabase.table("agent_assignments").insert(assignment_data).execute()
            assignment = assignment_result.data[0]
            
            # Update conversation status
            supabase.table("conversations").update({
                "status": "escalated",
                "escalated_at": "now()",
                "escalation_status": "assigned_to_agent"
            }).eq("id", conversation_id).execute()
            
            # Remove from queue if exists
            supabase.table("agent_queue").delete().eq("conv_id", conversation_id).execute()
            
            # Update agent status
            await self._update_agent_status(agent_id, "busy")
            
            logger.info(f"Successfully assigned conversation {conversation_id} to agent {agent_id}")
            
            return {
                "success": True,
                "assignment_id": assignment["id"],
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "status": "assigned"
            }
            
        except Exception as e:
            logger.error(f"Failed to assign conversation to agent: {str(e)}")
            raise
    
    async def _find_best_available_agent(self, org_id: str, kb_id: Optional[str]) -> Optional[str]:
        """Find the best available agent for a conversation."""
        try:
            # Get available agents for the organization
            agents_result = supabase.table("support_agents").select("*").eq("org_id", org_id).eq("is_active", True).execute()
            
            if not agents_result.data:
                return None
            
            available_agents = []
            for agent in agents_result.data:
                # Check if agent is available
                if agent["status"] != "available":
                    continue
                
                # Check current workload
                workload = await self._get_agent_workload(agent["id"])
                if workload >= agent["max_concurrent_conversations"]:
                    continue
                
                # Check shift hours (if configured)
                if agent["shift_start"] and agent["shift_end"]:
                    if not self._is_within_shift_hours(agent):
                        continue
                
                available_agents.append({
                    "id": agent["id"],
                    "workload": workload,
                    "max_concurrent": agent["max_concurrent_conversations"],
                    "skills": agent.get("skills", [])
                })
            
            if not available_agents:
                return None
            
            # Sort by workload (lowest first) and skills match
            available_agents.sort(key=lambda x: x["workload"])
            
            return available_agents[0]["id"]
            
        except Exception as e:
            logger.error(f"Failed to find available agent: {str(e)}")
            return None
    
    async def _check_agent_availability(self, agent_id: str) -> bool:
        """Check if an agent is available for new assignments."""
        try:
            result = supabase.table("support_agents").select("status", "max_concurrent_conversations").eq("id", agent_id).single().execute()
            
            if not result.data:
                return False
            
            agent = result.data
            if agent["status"] != "available":
                return False
            
            # Check current workload
            workload = await self._get_agent_workload(agent_id)
            return workload < agent["max_concurrent_conversations"]
            
        except Exception as e:
            logger.error(f"Failed to check agent availability: {str(e)}")
            return False
    
    async def _get_agent_workload(self, agent_id: str) -> int:
        """Get current workload for an agent."""
        try:
            result = supabase.table("agent_assignments").select("id").eq("agent_id", agent_id).eq("status", "active").execute()
            return len(result.data) if result.data else 0
        except Exception as e:
            logger.error(f"Failed to get agent workload: {str(e)}")
            return 0
    
    def _is_within_shift_hours(self, agent: Dict[str, Any]) -> bool:
        """Check if current time is within agent's shift hours."""
        try:
            current_time = datetime.now().time()
            shift_start = agent.get("shift_start")
            shift_end = agent.get("shift_end")
            
            if not shift_start or not shift_end:
                return True  # No shift restrictions
            
            # Handle overnight shifts
            if shift_end < shift_start:
                return current_time >= shift_start or current_time <= shift_end
            else:
                return shift_start <= current_time <= shift_end
                
        except Exception as e:
            logger.error(f"Failed to check shift hours: {str(e)}")
            return True  # Default to available if can't determine
    
    async def _add_to_queue(
        self, 
        conversation_id: str, 
        conversation: Dict[str, Any], 
        priority: str
    ) -> Dict[str, Any]:
        """Add conversation to the agent queue."""
        try:
            # Get queue position
            queue_position = await self._get_next_queue_position(conversation["org_id"], priority)
            
            queue_data = {
                "conv_id": conversation_id,
                "org_id": conversation["org_id"],
                "kb_id": conversation.get("kb_id"),
                "queue_position": queue_position,
                "priority": priority,
                "status": "waiting",
                "timeout_minutes": self.max_queue_timeout
            }
            
            queue_result = supabase.table("agent_queue").insert(queue_data).execute()
            queue_entry = queue_result.data[0]
            
            # Schedule timeout check
            asyncio.create_task(self._schedule_queue_timeout(queue_entry["id"], self.max_queue_timeout))
            
            logger.info(f"Added conversation {conversation_id} to queue at position {queue_position}")
            
            return {
                "success": True,
                "queue_id": queue_entry["id"],
                "conversation_id": conversation_id,
                "queue_position": queue_position,
                "status": "queued"
            }
            
        except Exception as e:
            logger.error(f"Failed to add conversation to queue: {str(e)}")
            raise
    
    async def _get_next_queue_position(self, org_id: str, priority: str) -> int:
        """Get the next queue position for the organization and priority."""
        try:
            # Get the highest position for this priority level
            result = supabase.table("agent_queue").select("queue_position").eq("org_id", org_id).eq("status", "waiting").order("queue_position", desc=True).limit(1).execute()
            
            if result.data:
                return result.data[0]["queue_position"] + 1
            else:
                return 1
                
        except Exception as e:
            logger.error(f"Failed to get queue position: {str(e)}")
            return 1
    
    async def _schedule_queue_timeout(self, queue_id: str, timeout_minutes: int):
        """Schedule a timeout check for a queue entry."""
        try:
            await asyncio.sleep(timeout_minutes * 60)
            
            # Check if still in queue
            queue_result = supabase.table("agent_queue").select("status").eq("id", queue_id).single().execute()
            
            if queue_result.data and queue_result.data["status"] == "waiting":
                # Remove from queue and mark as timeout
                supabase.table("agent_queue").update({"status": "cancelled"}).eq("id", queue_id).execute()
                logger.info(f"Queue entry {queue_id} timed out after {timeout_minutes} minutes")
                
        except Exception as e:
            logger.error(f"Failed to process queue timeout: {str(e)}")
    
    async def _update_agent_status(self, agent_id: str, status: str):
        """Update agent status."""
        try:
            supabase.table("support_agents").update({
                "status": status,
                "updated_at": "now()"
            }).eq("id", agent_id).execute()
        except Exception as e:
            logger.error(f"Failed to update agent status: {str(e)}")
    
    async def inject_agent_response(
        self, 
        conversation_id: str, 
        agent_id: str, 
        message: str, 
        message_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Inject an agent response into a conversation."""
        try:
            logger.info(f"Injecting agent response for conversation {conversation_id}")
            
            # Verify agent has access to this conversation
            assignment_result = supabase.table("agent_assignments").select("*").eq("conv_id", conversation_id).eq("agent_id", agent_id).eq("status", "active").execute()
            
            if not assignment_result.data:
                raise ValueError("Agent does not have an active assignment for this conversation")
            
            # Create agent response
            response_data = {
                "conv_id": conversation_id,
                "agent_id": agent_id,
                "message_type": message_type,
                "content": message,
                "metadata": metadata or {}
            }
            
            response_result = supabase.table("agent_responses").insert(response_data).execute()
            response = response_result.data[0]
            
            # Update conversation with agent message
            supabase.table("messages").insert({
                "conv_id": conversation_id,
                "sender": "ai",  # We use 'ai' sender for agent responses too, with metadata
                "content": message,
                "agent_response": True,
                "agent_id": agent_id
            }).execute()
            
            # Log the agent response injection
            supabase.table("integration_events").insert({
                "integration_id": None,  # No external integration
                "event_type": "agent_response_injected",
                "payload": {
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                    "message_type": message_type,
                    "response_id": response["id"]
                },
                "status": "completed"
            }).execute()
            
            logger.info(f"Successfully injected agent response for conversation {conversation_id}")
            
            return {
                "success": True,
                "response_id": response["id"],
                "conversation_id": conversation_id,
                "agent_id": agent_id
            }
            
        except Exception as e:
            logger.error(f"Failed to inject agent response: {str(e)}")
            raise
    
    async def escalate_conversation(
        self, 
        conversation_id: str, 
        reason: str, 
        priority: str = "high",
        escalated_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Escalate a conversation to human agents."""
        try:
            logger.info(f"Escalating conversation {conversation_id} to human agents")
            
            # Get conversation details
            conv_result = supabase.table("conversations").select("*").eq("id", conversation_id).single().execute()
            if not conv_result.data:
                raise ValueError("Conversation not found")
            
            conversation = conv_result.data
            
            # Update conversation status
            supabase.table("conversations").update({
                "status": "escalated",
                "escalated_at": "now()",
                "escalated_by": escalated_by
            }).eq("id", conversation_id).execute()
            
            # Attempt to assign to an agent
            assignment_result = await self.assign_conversation_to_agent(
                conversation_id=conversation_id,
                assignment_type="escalation",
                priority=priority,
                assigned_by=escalated_by
            )
            
            # Log the escalation
            supabase.table("integration_events").insert({
                "integration_id": None,
                "event_type": "conversation_escalated",
                "payload": {
                    "conversation_id": conversation_id,
                    "reason": reason,
                    "priority": priority,
                    "assignment_result": assignment_result
                },
                "status": "completed"
            }).execute()
            
            logger.info(f"Successfully escalated conversation {conversation_id}")
            
            return {
                "success": True,
                "conversation_id": conversation_id,
                "escalation_reason": reason,
                "assignment_result": assignment_result
            }
            
        except Exception as e:
            logger.error(f"Failed to escalate conversation: {str(e)}")
            raise
    
    async def complete_agent_assignment(self, agent_id: str, conversation_id: str, notes: Optional[str] = None):
        """Complete an agent assignment."""
        try:
            logger.info(f"Completing agent assignment: agent {agent_id}, conversation {conversation_id}")
            
            # Update assignment status
            supabase.table("agent_assignments").update({
                "status": "completed",
                "completed_at": "now()",
                "notes": notes
            }).eq("agent_id", agent_id).eq("conv_id", conversation_id).execute()
            
            # Update agent status back to available
            await self._update_agent_status(agent_id, "available")
            
            # Update conversation status
            supabase.table("conversations").update({
                "status": "resolved_human",
                "resolved_at": "now()"
            }).eq("id", conversation_id).execute()
            
            logger.info(f"Successfully completed agent assignment")
            
        except Exception as e:
            logger.error(f"Failed to complete agent assignment: {str(e)}")
            raise
    
    async def transfer_conversation(
        self, 
        conversation_id: str, 
        from_agent_id: str, 
        to_agent_id: str, 
        reason: Optional[str] = None,
        transferred_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """Transfer a conversation from one agent to another."""
        try:
            logger.info(f"Transferring conversation {conversation_id} from agent {from_agent_id} to {to_agent_id}")
            
            # Verify destination agent is available
            if not await self._check_agent_availability(to_agent_id):
                raise ValueError("Destination agent is not available")
            
            # Update original assignment
            supabase.table("agent_assignments").update({
                "status": "transferred",
                "completed_at": "now()",
                "notes": f"Transferred to agent {to_agent_id}. Reason: {reason}"
            }).eq("agent_id", from_agent_id).eq("conv_id", conversation_id).execute()
            
            # Create new assignment
            assignment_data = {
                "conv_id": conversation_id,
                "agent_id": to_agent_id,
                "assigned_by": transferred_by,
                "assignment_type": "manual",
                "priority": "normal",
                "status": "active",
                "notes": f"Transferred from agent {from_agent_id}. Reason: {reason}"
            }
            
            assignment_result = supabase.table("agent_assignments").insert(assignment_data).execute()
            
            # Update agent statuses
            await self._update_agent_status(from_agent_id, "available")
            await self._update_agent_status(to_agent_id, "busy")
            
            logger.info(f"Successfully transferred conversation {conversation_id}")
            
            return {
                "success": True,
                "conversation_id": conversation_id,
                "from_agent_id": from_agent_id,
                "to_agent_id": to_agent_id,
                "transfer_reason": reason
            }
            
        except Exception as e:
            logger.error(f"Failed to transfer conversation: {str(e)}")
            raise


# Global human agent workflow service instance
human_agent_workflow = HumanAgentWorkflowService()