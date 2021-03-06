#ifndef _COS_IDL_LOCK_H
#define _COS_IDL_LOCK_H

#include "cidl_gen.h"

service_global_info = {
	service		       = lock,

        desc_close_self_only   = true,
        desc_dep_create_none   = true,
        desc_global	       = false,
        desc_block	       = true,
        desc_has_data	       = false,
        resc_has_data	       = false,
};

sm_creation(lock_component_alloc);
sm_transition(lock_component_alloc, lock_component_free);
sm_transition(lock_component_alloc, lock_component_pretake);
sm_transition(lock_component_pretake, lock_component_take);
sm_transition(lock_component_take, lock_component_release);
sm_transition(lock_component_release, lock_component_pretake);
sm_transition(lock_component_release, lock_component_free);
sm_terminal(lock_component_free);

sm_block(lock_component_take);
sm_wakeup(lock_component_release);

desc_data_retval(ul_t, lock_id)
lock_component_alloc(spdid_t desc_data(spdid));

int 
lock_component_take(spdid_t spdid, 
		    ul_t desc(lock_id), 
		    u32_t desc_data(thd_id));

int
lock_component_pretake(spdid_t spdid, 
		       ul_t desc(lock_id), 
		       u32_t thd_id);

int 
lock_component_release(spdid_t spdid, 
		       ul_t desc(lock_id));

int 
lock_component_free(spdid_t spdid, 
		    ul_t desc_terminate(lock_id));

#endif  // _COS_IDL_LOCK_H
